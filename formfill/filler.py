"""Fills a *copy* of the PDF template with the approved mappings. Never
opens the original template for writing.

Two things learned the hard way while building the full version of this
project, both preserved here because they're correctness fixes, not
unnecessary abstraction:

1. An unresolved field is explicitly reset to "/Off" rather than left
   untouched. Some real-world templates ship with a default selection
   already baked in (e.g. the first radio option) -- leaving an unresolved
   field alone would let that arbitrary default silently stand in as if it
   were a real, sourced answer.
2. `writer.set_need_appearances_writer(True)` is deliberately NOT called.
   It makes some PDF viewers (poppler included) fall back to a generic box
   for radio/checkbox widgets instead of their actual appearance stream --
   even though the underlying value is set correctly. `auto_regenerate`
   handles text fields fine on its own.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter

from formfill.form import FormField
from formfill.matcher import Mapping

_NEUTRALIZABLE = {"radio", "checkbox", "dropdown"}


def fill_form(
    template_path: str | Path,
    output_path: str | Path,
    fields: list[FormField],
    mappings: list[Mapping],
) -> None:
    template_path, output_path = Path(template_path), Path(output_path)
    if template_path.resolve() == output_path.resolve():
        raise ValueError("output_path must not be the same file as template_path")

    approved = {m.field_name: m.value for m in mappings if m.status == "APPROVED"}

    values = {}
    for f in fields:
        if f.name in approved:
            values[f.name] = approved[f.name]
        elif f.kind in _NEUTRALIZABLE:
            values[f.name] = "/Off"

    writer = PdfWriter(clone_from=str(template_path))
    for page in writer.pages:
        writer.update_page_form_field_values(page, values, auto_regenerate=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as fh:
        writer.write(fh)
