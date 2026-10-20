"""The small heading shown at the top of each pane (Transcript, Playback, Library, Clip Editor)."""
from PySide6.QtWidgets import QLabel


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight: bold; padding-bottom: 2px;")
    return label
