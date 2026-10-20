"""Tag types (string / int / bool): editor controls, library columns and filters, persistence, old-file migration."""
import json, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os, tempfile
os.environ.setdefault("SNAPPER_DATA", tempfile.mkdtemp())   # tests never touch the real projects
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from snapper.clips_panel import ClipsPanel
from snapper.editor import INT_UNSET, ClipEditor
from snapper.model import Clip, ClipFilter, ClipTableModel, Project

app = QApplication(sys.argv)
tmp = Path(tempfile.mkdtemp())
media = tmp / "ep.mkv"

# --- a new project has only 'character': no overlap/residue flags unless the user adds them
p = Project(media)
assert p.tag_types == ["character"] and p.tag_kinds == {"character": "string"}
ed = ClipEditor(p)
assert not ed.bool_boxes and not ed.int_boxes and list(ed.tag_boxes) == ["character"]
print("ok   new project: only 'character', no flags")

p.add_tag_type("loudness", "int")
p.add_tag_type("overlap", "bool")
p.add_tag_type("bad", "nonsense")
p.add_tag_type("loudness", "bool")   # duplicate name ignored
assert p.tag_types == ["character", "loudness", "overlap"] and p.tag_kinds["loudness"] == "int"
ed.rebuild()
assert list(ed.int_boxes) == ["loudness"] and list(ed.bool_boxes) == ["overlap"]
assert ed.int_boxes["loudness"].value() == INT_UNSET and not ed.bool_boxes["overlap"].isChecked()
print("ok   int and bool tag types get a spin box and a checkbox; bad kind / duplicate rejected")

ed.set_range(1.0, 2.0)
ed.tag_boxes["character"].setCurrentText("Alastor"); ed._tag_edited("character")
ed.int_boxes["loudness"].setValue(7)
ed.bool_boxes["overlap"].setChecked(True)
assert ed.clip.tags == {"character": "Alastor", "loudness": 7, "overlap": True}, ed.clip.tags
ed.bool_boxes["overlap"].setChecked(False)
ed.int_boxes["loudness"].setValue(INT_UNSET)
assert ed.clip.tags == {"character": "Alastor"}, ed.clip.tags
ed.int_boxes["loudness"].setValue(3); ed.bool_boxes["overlap"].setChecked(True)
print("ok   editing stores values; unchecked / unset removes the tag")

c = p.add(Clip(1.0, 2.0, "a", True, dict(ed.clip.tags)))
p.add(Clip(3.0, 4.0, "b", True, {"character": "Alastor", "loudness": 5}))
p.add(Clip(5.0, 6.0, "c", True, {"character": "Husk", "overlap": True}))
assert p.values("character") == ["Alastor", "Husk"] and "loudness" not in p.tag_values
assert p.filter_values("overlap") == ["Yes", "No"] and p.filter_values("loudness") == ["3", "5"]
model = ClipTableModel(p); flt = ClipFilter(model)
assert "Flags" not in model.columns() and model.columns() == ["#", "In", "Dur", "character", "loudness", "overlap", "Text", "Export"]
def shown(): return [flt.index(r, 0).data() for r in range(flt.rowCount())]
assert shown() == [1, 2, 3]
flt.set_filter("overlap", "Yes"); assert shown() == [1, 3]
flt.set_filter("overlap", "No"); assert shown() == [2]
flt.set_filter("overlap", None); flt.set_filter("loudness", "5"); assert shown() == [2]
flt.set_filter("loudness", None)
col = model.columns().index("overlap")
assert model.index(0, col).data() == "✓" and model.index(1, col).data() == ""
print("ok   library columns and filters for int and bool")

panel = ClipsPanel(p)   # builds a filter dropdown per tag; renaming only for text tags
assert sum(1 for _ in range(panel.filter_row.count())) == 3 + 1
print("ok   library panel builds")

p.save()
q = Project(media)
assert q.tag_kinds == p.tag_kinds and [c.tags for c in q.clips] == [c.tags for c in p.clips]
print("ok   saved and reloaded")

# --- a file from before tag types: flags move into bool tags, only the ones actually used
old = tmp / "old.mkv"
(tmp / "old.mkv.snapper.json").write_text(json.dumps({
    "version": 1, "tag_types": ["character"], "flag_types": ["overlap", "residue"], "tag_values": {"character": ["A"]},
    "clips": [{"id": 1, "start": 1, "end": 2, "text": "x", "tags": {"character": "A"}, "flags": ["overlap"]},
              {"id": 2, "start": 3, "end": 4, "text": "y", "tags": {}, "flags": []}]}))
o = Project(old)
assert o.tag_types == ["character", "overlap"] and o.tag_kinds["overlap"] == "bool", o.tag_types
assert o.clips[0].tags == {"character": "A", "overlap": True} and o.clips[1].tags == {}
print("ok   old flags migrate to bool tags (unused 'residue' is dropped)")
print("TAG KINDS OK")
