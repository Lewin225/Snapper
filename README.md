Snapper is a tool for quickly cutting hundreds of audio clips from a video

It was part of my game tooling, but it's so useful on it's own I split it off

* Wide format support via mpv
* Rapid seeking with optional proxy generation
* Seek and select by transcript, either from your video, or an external srt file
* Optional automatic transcription generation via WhisperX <- very good ([more information](#optional-tools-whisperx-and-audio-separator))
* Optional automatic background removal for vocals via audio-separator ([more information](#optional-tools-whisperx-and-audio-separator))
* GPU Accelerated where available
* Custom project level tagging setup
* Custom tags can be exported into audio files
* Custom tags can drive export into separate folder
* Automatic realtime export as you work
* Automatic re-export of clips on path or structure change
* Optional tape scrubbing mode with free or pitch corrected audio
* Auto saved projects that resume to where you left off

To run snapper, you can download the provided flatpak. or download the source and use run.sh, or compile the flatpak yourself. or some fourth option. it's all yours baby ([more information](#running-it))

* If using run.sh - it will warn you if your system is missing required components and tell you how to install them (it doesn't install anything itself)
* If using the flatpak, the required components are bundled

Snapper has no hard hardware requirements, but you'll want to let it use your gpu for model based transcription and noise removal or you'll be waiting a million years

Snapper can either be ran on it's own, or used to open a video file. which will start a new project for that video if one doesn't already exist


Setting up WhisperX (first time only)
WhisperX is what writes the transcripts. It isn't bundled, it's a few GB of Python packages, so Snapper installs it for you the first time you ask for one
1. Open a video, then click Transcript -> Generate using WhisperX -> From original audio
2. If WhisperX isn't found you'll get the setup window, pick a runtime
	* GPU (NVIDIA CUDA) - about 5 GB download, fast
	* CPU only - about 1 GB download, many times slower. Fine to try it out, painful for a whole episode
3. Click "Install separately, just for Snapper"
	* It goes in its own private Python environment in Snapper's data folder, your system Python isn't touched
	* There's a progress bar with the download rate and time left, the big packages take a while
	* You need about 12 GB free
4. When it finishes the transcript starts straight away. The first one also downloads the speech model (about 3 GB), after that it's already there
5. Other options if you'd rather not
	* "Install into my system Python" - goes into ~/.local only, it will ask first if your distro blocks pip installs
	* "Use my own installation..." - point it at a Python that already has whisperx, torch and torchaudio. Snapper installs whisperx 3.8.6 with torch and torchaudio 2.8.0 if you want to match it
	* If you're using the flatpak it can only use an installation it can reach, so your own one needs to be in a folder the flatpak has access to
6. Installed environments live in Snapper's data folder, File -> Open the folder of installed environments takes you there. WhisperX and audio-separator each get their own, they aren't shared
	* If the install fails, copy the last few lines of the error into an issue on GitHub


Typical workflow looks like this
1.Open a video, or start a new snapper project and select one

2.Snapper will start generating a proxy video for faster scrubbing, if you have fast storage, you can turn it off in View->Use Scrub Proxy

3. Open a transcript, using either
	* "Generate using WhisperX" ([more information](#optional-tools-whisperx-and-audio-separator)) - 99% of the time this is the best option, generates solid, accurate transcription with word level timings giving you great select to clip behaviour. will also populate the wave view with overhead words and allow selection snapping
	
	* "Load from video" - Load the transcript from the video subtitles, usually not accurate enough for clipping work, but you can still navigate with it - will present a list of subtitles if there's more than one.
	
	* "Import srt file" - same as embedded but you can use your own file, ymmv

4. Play the video using the Play and Stop buttons under the video in the Playback panel, Pause replaces Play as needed

5. Try clicking on the transcript to navigate the video, clicking an entry will advance the video to it's start and select the clip in the editor based on the start and end of the line. If the video was playing, it'll continue playing

6. If you have selected a clip already, you can deselect it with escape, or by clicking "Deselect Clip in the Playback panel"

7. The waveform should be visible in the clip editor by now
	* With no clip selected - drag the wave left and right to scrub it
	* Click anywhere on the wave to seek to that point
	* Scroll on the waveform to change the zoom level
	* If you used the whisper subtitles, you can see the individual words up above the wave
	
8. Make a clip
	* Hold right click on the wave until your cursor changes to a cross
	* Drag right till you've got the selection you want
	* If you've got whisper subs, you can click a line in the transcript, or a word in the waveform
	* Any method of clip selection will focus it in the wave viewer
	
9. Adjust your clip
	* Drag the green handle to move the start point
	* Drag the red handle to adjust the out point
	* You can also drag the in, out and length value fields below left and right if you prefer
	* Press P or click "Play Clip" to preview the clip, it will automatically stop at the end, and play from the start on the next click
	* Whisper users - You can check "Snap to words" to make the in and out positions do that thing that the checkbox says when dragged
	* You'll notice the waveform automatically scales to fit the full height of the window, this doesn't change the export or playback volume, it's just a visual aid

10. Tag your clip
	* Tags are a per project setting
	* Tags are exported in the audio metadata for each clip
	* The default tag is character (string)
		* You can add another tag via Tags->Add Tag Type:
			* Enter a tag name
			* Choose the type - String, Boolean (Yes/No) or Integer (Number)
			
	* If it's text or number, type the text and press enter to confirm
		* For text, If you've typed it before, it will appear in the dropdown
		* The first 9 character names entered are added as keyboard shortcuts (1-9)
	* For booleans just check the box
	
11. Add your text
	* Snapper makes a best guess on what text is in your clip, and is accurate on whisper transcriptions, but you can revise the text here
	
12. Save your clip
	* Click "Save to library" or press enter 
	
13. Managing your clips
	* Your clip will now appear in the library in the right pane
	* Click a clip to reopen it
	* Click the clip again to play it
	* Because you're editing a clip, the "Save to library" in the clip editor becomes "Done"
	* Changes make to this existing clip in the clip editor will apply automatically
	* Clicking done just takes you back to whatever new clip you were editing
	* You can filter your clips from the top of the library view
	* Right click a clip to duplicate or delete it
	
14. Exporting your clips
	* The export menu will be disabled on a new project, first you'll have to set up the export
	* Click the "Export Settings" button at the bottom of the library
	(Image of export folder to go here)
	* For the Export folder - click browser and select an EMPTY folder
		* It's not required to be empty, but when auto export is enabled snapper will delete, rename and move files in realtime within this folder to match the export options you choose
		* If you pick a full one and it deletes something that's on you
		* Using the flatpak version this may show as /run/user/1000/doc/(random), after selection, it will go where you selected regardless
	* Enter a file name, without the file extension - Make sure to add a placeholder or they'll all be the same name and won't write. the default file name will work for most projects
	* Clip text in the file name will be "close enough" - some characters aren't allowed in filenames, check your os documentation for this
	* Choose your file format, Channels, Sample Rate, Bit Depth. The defaults will work for most
	* "Clip Text Goes In" - Choose where in the file the full clip text will be placed, each file type has slightly different tag fields to choose from
	* "Add the clip's tags to the file" - Inserts all your tag data into one of the tag fields, on mp3 this is a custom field called snpr containing json
	* Folders, Check each tag to make it a folder in your export, this let's you organise the output based on the tags. eg by character, speaking volume, emotion etc...
	* Folders - Select a tag then click move up / move down to change it's position in the folder structure, the highest one is the parent, each one down is a child
	* Click "Okay" to confirm the export settings
	
15. Running the export
	* Click "Export" in the Library (Bottom Right) to manually export your clips
	* Tick "Auto Export" - your clips will be exported as soon as you create or modify them, including moving them around as you retag - You can continue to work and create new clips with this on

16. Where my clips at?
	* Right click any clip (after export has run) in the Library and select "Open containing folder" to find it
	* Same, but click "Open in system app" to play it in whatever your default app is
	
17. Background noise removal (For Clipping + Exports)
	* Snapper can remove background noise from your source audio and will give very clean results for most tv shows, with heavy musical sequences as the exception
	* You'll want about 12 GB free. The GPU install is about 5 GB, the CPU one about 1 GB, and the first run downloads the audio model (about 0.7 GB)
	* If your pc is up to the task - click "Audio" on the top menu bar
	* Click "Processing Model"
		* These three models are provided by audio-separator and were picked as they gave good results
		* Choose the top one, you can reduce this down if it takes too long or you have memory issues
	* Click Audio -> "Generate processed audio using audio-separator" ([more information](#optional-tools-whisperx-and-audio-separator))
	* The setup will check you have the required extra packages and prompt you to install or find them
		(Image of setup screen here)
		* Choose a runtime (Gpu/Cpu) and click "Install separately, just for Snapper"
		* If you don't trust the auto download (Fair tbh..), or want to use shared libraries - click "Use my own installation" and point it at a python install that meets the requirements
		* It needs audio-separator, torch (2.3 or newer) and onnxruntime (onnxruntime-gpu for the GPU), the setup window checks and tells you what's missing
		* Snapper installs audio-separator 0.47.1 without diffq, which is only used by the Demucs models (Snapper doesn't use them) and needs a compiler to build on newer Python versions. You can leave it out too
		* The download is about 5 GB for GPU, about 1 GB for CPU, then the model (about 0.7 GB) the first time you run it
	* Once installed - noise removal will automaticlly start
	* Track its progress in the very bottom right
	* You don't have to wait for it to finish, The % that's finished is added to your project as you work
	* Switch to the new audio in the clip editor by clicking "Processed"
	* Background audio will remain visible on the wave, but faded out
	* Exports use whichever audio the clip is set to. Click "Processed" on a clip to cut it from the clean audio, clips left on "Original" export the original.


Extras

Scrub sound
	* Dragging the wave with no clip selected plays the audio under the cursor, like scrubbing a tape. Faster drag = faster, higher sound, drag backwards and it plays backwards, hold still and it goes quiet
	* It uses the processed audio if the clip is set to it and it exists, otherwise the original
	* Pick how it sounds in Audio -> "Scrub sound"
		* Tape - the audio under the cursor at the speed you drag, pitch follows the speed. This is the default
		* Granular - same idea but the pitch stays put, so it sounds more like a stuttering voice than a tape, ytp style
		* Playback - short pieces of the video's audio through the player, it's the lightest but isn't very fun
		* Muted - no sound while scrubbing
	* It follows the volume slider and mute, if it's too loud or quiet check those first


## Running it

Flatpak (from a release bundle):

    flatpak install --user Snapper.flatpak
    flatpak run io.github.Lewin225.Snapper

Without Flatpak, with pip or pipx (Linux; other platforms are not tested). Snapper uses your system's **libmpv** and **ffmpeg**
(with the `libx264` and `libmp3lame` encoders, for the scrub proxy and MP3 export; stock Fedora ffmpeg lacks them, install
ffmpeg from [RPM Fusion](https://rpmfusion.org)). Install those first, for example:

    sudo dnf install mpv-libs ffmpeg        # Fedora        (Debian/Ubuntu: sudo apt install libmpv2 ffmpeg)
    pipx install https://github.com/Lewin225/Snapper/releases/download/v1.0.0/snapper-1.0.0-py3-none-any.whl
    snapper [video-or-project]

If libmpv or ffmpeg is missing, Snapper says so at start and shows the command for your distribution. A missing encoder is
reported only when you use the feature that needs it (the scrub proxy falls back to the original video; MP3 export asks you to
pick WAV or fix ffmpeg).

From a checkout:

    pip install -r app/requirements.txt     # PySide6, python-mpv, numpy
    ./run.sh [video-or-project]

With no argument Snapper shows a start screen with your recent projects. Opening a video asks whether to resume its
project, if one exists; opening a project file opens it.

### Optional tools: WhisperX and audio-separator
Transcribing and vocal isolation use big Python packages (PyTorch and friends), so they are not part of Snapper. The first
time you use *Generate using WhisperX* (Transcript menu) or *Generate processed audio using audio-separator* (Audio menu), Snapper checks
what is missing and offers to install it for a **GPU or a CPU**: *just for Snapper* (a private environment in the app's data
folder), into your *system Python*, or you can point it at an installation you already have. A GPU is strongly recommended
(about 5 GB download); everything else works without either tool. Loading subtitles from the video or an `.srt` file needs
nothing extra.

**Processed audio:** *Audio → Generate processed audio using audio-separator* removes the music and effects, leaving the
dialogue. It runs in the background and can be used as soon as the first part is done (playback returns to the original beyond
the finished part). The processed audio sits beside the original: pick *Original* or *Processed* per clip in the clip editor
(or press `V`); the waveform, what you hear and what gets exported all follow that choice. *Audio → Import custom processed
audio…* lets you use an audio file made with another model or tool instead (it is placed at the start of the episode and
padded or cut to its length). *Transcript → Generate using WhisperX → From processed audio* often hears the words better.

## Tests

    app/tests/run_all.sh        # fetches the test video on first use

The tests drive the real app with a Qt window and mpv; they need a display (or `QT_QPA_PLATFORM=offscreen` for some) and a
GPU is optional. See `app/tests/media/README.md` for the test media and its credits.

## Licence

Snapper is licensed under the **GNU Affero General Public License, version 3 or later** (see [LICENSE](LICENSE)).

Third-party software it uses or ships:

| | Licence |
|---|---|
| Qt 6 / PySide6 | LGPL-3.0 (or GPL) |
| python-mpv | GPL-2.0+ or LGPL-2.1+ |
| libmpv, libplacebo, libass | GPL-2.0+ / LGPL-2.1+ (the Flatpak's mpv is GPL) |
| FFmpeg (separate program; the Flatpak build is GPL, with x264) and LAME | GPL-2.0+ / LGPL |
| numpy | BSD-3-Clause |
| WhisperX, PyTorch, torchaudio, faster-whisper, CTranslate2, transformers | BSD / MIT / Apache-2.0 (installed separately, not bundled) |

The Flatpak manifest in `flatpak/` lists the exact source of everything it builds. The speech models WhisperX downloads
have their own licences.

Test video: *Tears of Steel* © Blender Foundation | mango.blender.org, CC BY 3.0 (downloaded when you run the tests, never bundled).
