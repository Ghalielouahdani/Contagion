# DeFi Contagion Visual System

## Art Direction

The app should feel like a financial editorial instrument: quiet, exact, tense, and carefully composed. It should avoid generic SaaS gloss. The layout is typography-led, left-aligned, and spacious, with a visible grid, hairline dividers, and one confident accent used with restraint.

Reference mood: nickpyl.space restraint, editorial pacing, asymmetry, small labels, large type, and whitespace that feels intentional rather than empty.

## Type

- Display: `Newsreader`, `Iowan Old Style`, `Georgia`, serif.
  - Used for page titles and large financial figures.
  - Chosen because it feels like financial editorial publishing: high-contrast, literary, precise, and less default-dashboard than a neutral sans heading.
- Text: `IBM Plex Sans`, `Inter`, system sans.
  - Used for UI, labels, tables and controls.
  - Chosen because it has engineered clarity and a slightly technical voice without feeling like a generic app template.
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
- Each position card carries a low-profile stress rail derived from conditional loss over gross exposure. It adds risk texture without changing compact card dimensions.
- Cross-highlighting links KPI hover, selected detail card, peer cards and table rows. Nothing should feel stuck; hover is temporary, selection is explicit.
- Table rows are clickable financial records: quiet by default, accent rail and ink shift on hover/selection.
- The chosen font pairing is:
  - Display: `Newsreader`, then system serif fallbacks for high-end editorial tension.
  - UI/text: `IBM Plex Sans`, then `Inter`/system for precise controls and dense financial labels.

## Scenario Lab Vertical Slice

- Scenario Lab is the second slice and the reference for interactive controls.
- The layout reads like an editorial stress-testing desk: presets form a low, gridded index; controls sit in a tighter right rail; charts occupy the main reading plane.
- Preset cards should not look like equal SaaS tiles. They use hairline dividers, a small accent rule, quiet uppercase labels and only one elevated selected state.
- Controls are tactile but restrained: thin range tracks, accent-filled thumbs, small-caps labels, tabular values, and a single accent run button.
- Data visuals use the same neutral/accent encoding everywhere:
  - Before/current/reference values: muted neutral.
  - After/stressed/selected values: strong ink.
  - Risk movement: semantic low/mid/high colors, never neon.
- Assistant surface follows the same craft: translucent editorial panel, sentence captions, soft alive orb, no generic chat-bubble color palette.
- Motion is staggered and quiet: cards rise 1-3px, panels fade/rise, orb breathes while idle, all disabled under reduced motion.

## Dependency Graph Vertical Slice

- The Dependency Graph is the bespoke network diagram slice.
- React Flow chrome is visually absorbed into the product system: controls, minimap and search panel use the same translucent editorial surfaces and hairline dividers.
- Nodes are not default graph boxes. They behave like labeled data plaques with one thin accent rule, small-caps type labels, soft depth and type-specific accent strokes.
- Hover and selected position create a focus mode:
  - The active contagion path keeps full opacity.
  - Unrelated nodes fade back.
  - Critical edges thicken, glow subtly and animate.
- Edges use smooth routing, quiet relation labels and arrowheads. Confidence colors stay calm and analytical.
- The graph background is a designed data plane: warm/dark surface, faint grid, paper grain and restrained depth.

## Decision Engine Vertical Slice

- The Decision Engine reads like an investment memo: the recommendation/verdict is the focal object, with the exit curve and table as supporting evidence.
- Exit fractions are inspectable by hovering/clicking the chart or rows; the same selected fraction drives the inspector callout.
- The chart keeps brush/zoom but styles it as part of the product, not a default Recharts widget.
- Position tabs use the same hover/selected language as the portfolio cards, so cross-highlighting feels consistent across views.
- The inspector uses one accent rule and editorial type for the verdict; warning and loss breakdown data stay quieter underneath.

## Login And Intro Vertical Slice

- The intro is a short cinematic brand reveal, not a loader: restrained orbit, accent line, grain, large editorial wordmark and calm fade into login.
- The login screen keeps the same minimal centered composition but gains a crafted product surface with one accent rail, hairline border and subtle depth.
- Forms remain quiet and accessible. Validation/focus states use the accent line and focus wash, not loud default outlines.
- Touch ID / passkey controls share the same physical hover language as the rest of the app.
