# Changelog

## 1.0.15

- Normal local classification now consolidates multiple Source ID comments when heading edits merge them into one source unit. It preserves the ID below the classification heading, or the first ID in the unit, and backs up the original before saving.
- Body text, nested headings, quoted markers, fenced code examples, and existing empty-parent ID relocation are preserved. Headings and ID comments inside fenced code do not act as classification boundaries or permanent IDs. IDs shared by separate units or files remain errors.
- Dry runs show retained and removed IDs. Classification reports include consolidated-unit and removed-marker counts; obsolete generated documents are cleaned up during the normal update.
- Generated image and document links consistently resolve Windows short path names before computing relative paths.
