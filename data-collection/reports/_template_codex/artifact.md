# 데이터 전처리 결과서 양식 실행 계약

## Reference

- Retained DOCX: `C:\Users\playdata2\Downloads\[데이터전처리] 데이터전처리결과서.docx`
- SHA-256: `264D1F1450AB327DD7C8F55563ACC9D812753D8246BA61038D66A4311C523D04`
- Rendered pages: 4
- Sections: 1
- Reference render: `C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection\reports\_template_codex\reference-render`
- Style evidence: `C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection\reports\_template_codex\template-style-evidence.json`

## Page system

- A4 portrait, 11909 × 16834 twentieths of a point.
- One section with a distinct first-page header and footer.
- Margins encoded by the source: top 1275.59, bottom 1559.06, left/right 992.13 twentieths of a point; header/footer distance 720.
- Page 1 is a cover with a full-page blue abstract background and bottom metadata table.
- Pages 2–3 are dense process/result pages; page 4 contains change history.
- Existing page breaks, first-page behavior, background image, headers, footers, and page numbering are preserve-only.

## Typography and components

- Primary typeface: Malgun Gothic. Source contains direct formatting and is the authority.
- Cover: black team line and bold black report title over the supplied blue background.
- Body section title: bold black text below a blue top rule with a teal terminal rule.
- Body headings: black and bold. Bullet/result text: vivid blue as supplied.
- Tables: light blue header fill, bold black header text, light gray borders, centered blue body text. Row sizing and cell padding follow the source.
- Footer page numbers and all recurring chrome are preserve-only.

## Content flow and slot map

- `word/document.xml/body/tbl[1]`: cover team/title; rewrite text only.
- `word/document.xml/body/tbl[2]`: stage, date, GitHub path, author; rewrite cell text only.
- `word/document.xml/body/tbl[3]`: body title; rewrite text only.
- Body paragraphs at direct child indexes 9–14: overview and source-analysis headings; rewrite text only.
- Body table at direct child index 15: 7 × 5 source/quality status matrix; rewrite all cell text.
- Body paragraph index 17 and table index 18: quality diagnosis and 6 × 4 processing matrix; rewrite text only.
- Body paragraphs 20–23: pipeline, procedure, and split recommendation; rewrite text only.
- Body table index 24: 6 × 6 normalized field rules; rewrite all cell text.
- Body paragraph index 26 and table index 27: downstream suitability and reproducibility, 12 × 4; rewrite all cell text.
- Body paragraph index 29 and table index 30: change history, 3 × 5; rewrite all cell text.
- Empty paragraphs, section properties, relationships, headers, footers, numbering, styles, theme, custom XML, and media are preserve-only.

## Package preservation

- Only `word/document.xml` may change.
- Preserve all other package parts and relationships byte-for-byte, including two headers, two footers, numbering, settings, styles, theme, custom XML, and `word/media/image1.png` / `image2.png`.
- The reference remains unchanged and must retain its recorded SHA-256.

## Fidelity gates

- Final page count remains four.
- Cover background, rules, metadata grid, table fills, borders, text colors, and page numbers remain visually source-derived.
- No text clips, overlaps, spills outside table cells, or changes page geometry.
- Every final page is rendered and inspected after authoring.
