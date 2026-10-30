# Export format (draft, format version 3)

Status: **format version 3, implemented in `app/snapper/id3.py` and `export.py` (`clip_tag`), except the timed-text parts, which wait for the chunk editor.** This describes what an exported clip should contain so that every format
(WAV, MP3, anything added later) carries the same information in the same way, and so that timed text (see "Timed text chunks") can
be added without redoing it. "Today" notes say what `app/snapper/export.py` does now. Choices that are still open are listed at the end.

## Goals

1. **One model, many containers.** A clip is described once (below); each format writes it with that format's own native fields.
2. **Visible to ordinary software.** Standard fields (title, artist, comment...) are real standard fields, so a music player, the
   Windows or KDE file manager, or a tag editor shows them. Nothing important lives only in a private blob.
3. **Lossless for scripts.** The complete data, with types, is also available as one JSON document (`snpr`) for tools that want it.
4. **Room for timing.** Times for pieces of the clip's text attach to the same model, in the places each container provides for them. Timing is optional: everything works without it.
5. **Safe to re-export.** A clip's export is out of date exactly when something that goes into the file changes (the export
   signature, `export.export_signature`). Changing the format version changes every signature once, so clips re-export once.

## Scope

The main consumer of exported files is the author's own software, which reads the `snpr` JSON (`TXXX:snpr`) and is the source of truth for
everything in the file. The standard frames are there so that other software sees the useful parts (title, comment, tags, chapters,
synchronised lyrics) without any help, but how well a given third-party player shows them is best effort.

Not part of this format, by decision: eLRC or LRC text in `USLT` (it stays plain text), sidecar subtitle or lyric files, RIFF `cue `/`LIST`
chunks in WAV. Reasons found by trying real software: video players (mpv-based Cine, MPC, Dikan) do not show ID3 lyrics as subtitles,
and Chronograph only reads `USLT` (and only when its "Prefer Embedded Lyrics" import option is on). Neither affects the main consumer.

What was seen working in real software with a prototype file (MP3 and WAV): Cine lists the chunks as chapters; Kid3 shows the tags and,
in its editor for the synchronised-lyrics frame, the three or 47 words with their times; mutagen reads every frame in both containers.

## The clip model

| Field | Type | Notes |
|---|---|---|
| `text` | string | The clip's text. May be empty. |
| `tags` | map name to value | Value is a string, an integer, or `true` (Yes/No tags are written only when ticked). Names are the project's tag names. |
| `chunks` | list, optional | Future. Timed pieces of the text, see below. |
| `format` | integer | 2 for this document. Written so a reader can tell. |

Times are relative to the clip so a file means the same wherever it goes.

### Timed text chunks

A chunk is a piece of the clip's text with a time span: `{"text": "pen", "start": 0.21, "end": 0.38}`, seconds relative to the
start of the clip. The model does **not** say what a chunk is. It can be a word, a syllable, a phrase or anything the person who made it chose:

- WhisperX gives one chunk per word (`Transcript` lines already hold `{text, start, end}` words; the clip's chunks are the ones inside the clip, shifted by its start).
- Subtitles, an imported `.srt` and hand-typed text have no timing, so a clip from them has no `chunks`.
- Later the user will be able to add or change chunks (there is no editor for it yet). They might split `dependency` into `de`, `pen`, `den`, `cy`, or join words into a phrase.

So every reader and writer treats `chunks` as optional and as arbitrary in size. Rules:

1. **Order and range.** Sorted by `start`, no overlaps, each inside the clip (0 to its length). They need not cover the clip: gaps (silence, untimed text) are allowed.
2. **The pieces make the text.** The chunk texts joined in order, with nothing added, are the clip's text apart from surrounding whitespace. So spaces belong to the chunk that precedes them: `"Hello "`, `"there"` for two words, but `"de"`, `"pen"`, `"den"`, `"cy"` for one word, with no spaces. (WhisperX words arrive without spaces; the exporter adds a space between them, as `Transcript.text_for` does.)
3. **Never disagree with the text.** The chunk editor will replace the current plain text editor, so the clip's text is *made of* its chunks: deleting text deletes its chunk, and there is no separate edit that could leave the two out of step. (A clip with no timing is a single untimed chunk of text.) The exporter still checks rule 2 and, if it fails, writes no timing rather than timing that contradicts the text.
4. **Precision.** Seconds as decimals in JSON (up to six places), whole milliseconds in `SYLT`.

## Where each part goes

### Clip text

Always written as the lyrics, `USLT` (ID3v2.3, in MP3 and in the WAV `ID3 ` chunk): that is the field players show as the text or
captions. It is not a setting. The same text with the time of each word goes in `SYLT` once words can be timed by hand (see "Timed text
chunks"); Export Settings lists both rows, read-only, in the table of what goes where, the second marked "not written yet". Because the
text has its own frame, no tag competes with it for a field (format version 2 let the settings send the text to Title, Comment or
Subtitle, which made a tag and the text fight over one frame).

### Tags

Each tag gets **its own field**, so a player can read it.

- Where a tag goes is set in the table in Export Settings (one row per tag). Until the user changes a row, a tag whose name
  (case-insensitive) is a well-known one is bound to the standard field (`date` and `year` only when the value is a four-digit year; if two tags are bound to one frame, the first gets it, the other becomes a `TXXX` frame and the dialog says so). The choices are
  Custom field (`TXXX`), Title, Artist, Album, Genre, Track, Year, Copyright, Comment and Subtitle. Only the rows that differ from the default are stored in the settings (`tag_frames`):

  | Tag name | ID3v2.3 frame |
  |---|---|
  | `title` | `TIT2` |
  | `artist` | `TPE1` |
  | `album` | `TALB` |
  | `genre` | `TCON` |
  | `track` | `TRCK` |
  | `date`, `year` | `TYER` |
  | `comment` | `COMM` |
  | `copyright` | `TCOP` |

  (The list is a proposal; it can grow. Names are matched exactly, never by guessing.)
- Any other tag, or one bound to Custom field, becomes a custom text frame, `TXXX` with the tag's name as the description
  (`TXXX:character`), keeping the name's capitalisation.
- Every tag is also in the `snpr` JSON, whatever field it went to (a tag named `artist` is both `TPE1` and in the JSON), with its real type.
- Values are text: strings as they are, integers in decimal. A Yes/No tag is written as its **label**, see "Yes/No labels" below.
- Character set: ISO-8859-1 when the text fits, otherwise UTF-16 with a byte-order mark (ID3v2.3, which Windows and older players read).

### Yes/No labels

A Yes/No tag has two labels, one for Yes and one for No. The same two strings are used everywhere the tag is turned into text:
the ID3 field, the `{tag}` file-name token, the tag folders and the library column. (Today the library and folders use "Yes"/"No"
(`tag_text` in `model.py`) while the file tag says `true`; this replaces both.)

- Each Yes/No tag type lets the user set the two strings. If they are not set, the labels are `<tagname>-yes` and `<tagname>-no`
  (for a tag called `shouting`: `shouting-yes`, `shouting-no`), which also reads sensibly in a folder name.
- Both labels are written, so an unticked tag is written too (as its No label), where earlier drafts left it out. A label has no invalid path characters, and the two must differ.
- The `snpr` JSON keeps the real value (`true` / `false`), not the label.
- Changing a label changes the file names, folders and file tags that use it, so affected clips re-export (the signature includes the label).
- A label is never empty (a Yes/No tag is a value, so both answers have a name). Clearing one puts the default back.

### The complete JSON (`snpr`)

Kept, and written the way it is today, plus the new members. It is the lossless copy, with types:

    {"format": 2, "text": "Hello there", "tags": {"character": "Alice", "shouting": true, "volume": 3},
     "chunks": [{"text": "Hello ", "start": 0.00, "end": 0.31}, {"text": "there", "start": 0.36, "end": 0.70}]}

(`chunks` appears only once timing exists.) It is a `TXXX:snpr` frame in the ID3 tag, in MP3 and WAV alike. It is meant for Snapper's own
tools and scripts; other software is not expected to understand it, only to leave it alone. Readers must ignore members they do not know.
*Today* `snpr` holds just the tags object, and in WAV it is a separate RIFF chunk named `snpr`.

## Containers

### MP3

One ID3v2.3 tag at the start of the file, written by Snapper (ffmpeg encodes only the audio, with its own tag writing off). Frames
in this order: the lyrics (`USLT`), the tags bound to standard fields, custom `TXXX` tags, `TXXX:snpr`, then (future, only when there are chunks) `SYLT`, `CTOC` and `CHAP`.
*Today* the tags go on ffmpeg's command line, which caps them at about 131,000 characters and fails with "Argument list too long"
above that; writing the tag ourselves removes the limit.

### WAV

RIFF chunks in this order:

| Chunk | Contents |
|---|---|
| `fmt `, `fact` (float only) | as today |
| `data` | the audio |
| `ID3 ` | the **same ID3v2.3 tag as the MP3**, byte for byte, so there is one metadata standard for every format |

Nothing else carries metadata: no `LIST/INFO`, no separate `snpr` chunk, no RIFF `cue ` points (the ID3 `CHAP` frames play that part). The ID3 chunk is the single place, as it is in MP3.
The chunk id is `ID3 ` (upper case; ffprobe read it back in a test with a hand-built chunk). Some software writes `id3 ` in lower case, so
Snapper's reader accepts both. Chunk sizes are padded to even length. Readers skip chunks they do not know, so players still open these files.

Consequence: tools that read only the older `LIST/INFO` fields (some basic players and the Windows file properties, as far as I know)
will show no title or comment for a WAV. Tools that read ID3 in WAV (ffmpeg and, I believe, Mp3tag and similar editors) show everything.

## Timing (future)

When a clip has `chunks`, the ID3 tag (MP3, and the WAV `ID3 ` chunk) carries them three ways, because different software reads different ones.
A clip without chunks writes none of these.

| Where | Contents | For |
|---|---|---|
| `TXXX:snpr` JSON | the `chunks` member, seconds relative to the clip | Snapper's own tools: the exact, complete form. |
| `SYLT` and `USLT` | one `SYLT` entry per chunk, timestamps in milliseconds; `USLT` holds the full text | Audio players (synchronised lyrics). The entry text is the chunk text including its trailing space, as karaoke-style players expect. |
| `CHAP` and `CTOC` | one `CHAP` frame per chunk (`c0`, `c1`...): start and end in milliseconds, the chunk text in a `TIT2` subframe; one `CTOC` frame (`toc`, top-level and ordered) listing them in order | DJ and editing tools (chapter / cue points). Chapter titles are written without the trailing space. |

Offsets in `CHAP` (the byte-position fields) are written as "unused" (`0xFFFFFFFF`), since the times are what matter.

Tested: ffprobe reads a `CHAP` + `CTOC` set back as chapters, with the right titles and times, both in an MP3 and in a WAV's `ID3 ` chunk
(and the files still decode). A prototype file with real WhisperX word times was opened in Cine (the words appear as chapters) and in
Kid3 (the tags show, and its editor for the synchronised-lyrics frame lists the three words with their times; its tag list shows that
frame's value as blank, as it does for chapters). Not tested: any other player's display of `SYLT`, and DJ tools. Check the tools people
use before promising it in the user guide. A per-clip sidecar file is the fallback for anything that proves unreliable.

`SYLT` content type: `1` (lyrics), because players that show synchronised text are most likely to look for that type. `2` (text
transcription) describes spoken word more exactly and Kid3 offers it, but whether players show it is untested.

## Compatibility and migration

- Format versions 2 and 3 change the signature input, so existing clips show as out of date and re-export once. Version 3 moves the clip text from the field chosen in the settings (default `COMM`) to `USLT`; an old project's text-field choice is ignored.
- WAV changes the most: the `LIST/INFO` and `snpr` chunks go, and everything moves into the `ID3 ` chunk. A reader of old WAV files has to
  fall back to those two chunks when there is no ID3 chunk (Snapper's `read_wav` should keep doing so). Scripts that read the old `snpr`
  chunk must read `TXXX:snpr` from the ID3 tag instead; MP3 scripts are unaffected.
- The user guide's description of the tag fields has to change with this (it currently says tags go into "one of the tag fields").

## Open decisions

1. **How a tag picks its field:** decided: by name (as above), and every tag is also in the `snpr` JSON regardless.
2. **Collisions:** decided: the text is always `USLT`, so only two tags bound to one field can collide; the first gets it, the other is a custom field and the settings dialog says so.
3. **Yes/No wording:** decided: two labels per Yes/No tag, defaulting to `<tagname>-yes` / `<tagname>-no`; see "Yes/No labels". Labels may not be empty.
4. **Keep `snpr`:** yes, as `TXXX:snpr`, for Snapper's own use (decided).
5. **ID3 version:** decided: 2.3 with UTF-16 (Latin-1 when the text fits), one version for MP3 and WAV.
6. **Timing in MP3:** decided: JSON, `SYLT`/`USLT` and `CHAP`/`CTOC` together (players and DJ tools read different ones).
7. **Timing in WAV:** decided: same as MP3, in the ID3 chunk.
8. **Joining rule for chunks:** decided: spaces belong to the preceding chunk.
9. **Text edited after timing:** decided: the chunk editor replaces the text editor, so deleting text deletes its chunk.
10. **Granularity hint:** decided: none; a chunk is just text and time.
