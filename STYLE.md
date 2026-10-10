# DeFi Contagion Visual System

## Art Direction

The app should feel like a financial editorial instrument: quiet, exact, tense, and carefully composed. It should avoid generic SaaS gloss. The layout is typography-led, left-aligned, and spacious, with a visible grid, hairline dividers, and one confident accent used with restraint.

Reference mood: nickpyl.space restraint, editorial pacing, asymmetry, small labels, large type, and whitespace that feels intentional rather than empty.

## Type

- Display: `Canela`, `Fraunces`, `Iowan Old Style`, `Georgia`, serif.
  - Used for page titles and large financial figures.
  - Chosen because the high contrast serif gives the product a more editorial, art-directed voice. Tightness comes from scale and line-height, not negative tracking.
- Text: `Geist`, `IBM Plex Sans`, `Inter`, system sans.
  - Used for UI, labels, tables and controls.
  - Chosen because the interface still needs precision and legibility.
- Mono numerals: `Roboto Mono`, `SFMono-Regular`, monospace.
  - Used for money, percentages, IDs and tabular data.
  - All financial values should use tabular numerals.

## Palette

Light mode:
- Page: warm ivory, not pure white.
- Ink: near-black with brown undertone.
- Muted text: graphite.
- Lines: low-contrast warm grey hairlines.
- Accent: mineral green, used for primary action and selected state.
- Risk semantics: amber, clay, and deep red. They should feel analytical, not alarming.

Dark mode:
- Page: charred black, not flat black.
- Ink: warm ivory.
- Lines: translucent warm grey.
- Accent: softer mineral green.
- Data surfaces stay low-glow and precise.

## Layout

- Use an editorial grid instead of equal SaaS cards.
- Hero/summary areas should have one large focal metric and smaller supporting facts.
- Cards can vary in span and density when the content deserves it.
- Keep sections unframed unless the content is a true object: table, chart, graph, control group.
- Use 1px hairline dividers over heavy shadows.

## Shape And Depth

- Radius: 2px to 8px. Pills only for tiny controls and chips.
- Shadows are rare, shallow and editorial. Do not use default component shadows.
- Add subtle page grain with CSS only.

## Motion

- Transitions should feel physical but quiet: 180ms for hover, 320ms for page entry.
- Stagger repeated objects by a few milliseconds.
- Respect `prefers-reduced-motion`.
- Hover motion is small: 1 to 3px shifts, no bounce.
- Selection changes use shared layout motion so objects feel re-composed, not swapped.
- Numeric figures count when their value changes, unless reduced motion is requested.

## Data Visuals

- Graphs and charts use thin strokes, quiet labels and tabular numerals.
- Confidence/risk color is semantic and consistent.
- Tooltips should look like annotated captions, not default chart popovers.
- Dependency graph nodes should feel like labels on a crafted network diagram, with custom strokes and restrained fill.

## Portfolio Vertical Slice

- The Portfolio Dashboard is the first fully art-directed slice.
- The KPI strip behaves like a financial table: one shared four-row grid for label, figure, spacer and footnote.
- The positions area is master-detail: one large selected position panel, three smaller peer cards, and temporary hover emphasis only on the card under interaction.
- Selected state uses the single mineral-green accent through surface tint, a hairline accent rule and a restrained active shadow.
- Figures use tabular numerals and animated count-up for legibility and polish.
- The chosen font pairing remains:
  - Display: `Canela`, then `Fraunces`, then system serif fallbacks for high-end editorial tension.
  - UI/text: `Geist`, then `IBM Plex Sans`, then `Inter`/system for precise controls and dense financial labels.
