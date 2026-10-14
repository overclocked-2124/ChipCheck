# Console design

A quiet engineering notebook: the setup is the primary document; navigation and the bench reference sit outside it. Data gets tables, not decorative cards. Follow the project HLD for ownership and approval language.

Applied skills: [redesign-existing-projects](https://github.com/Leonxlnx/taste-skill/tree/main/skills/redesign-skill) and [minimalist-ui](https://github.com/Leonxlnx/taste-skill/tree/main/skills/minimalist-skill).

Design variance: 4/10. Motion intensity: 1/10. Visual density: 4/10.

## Decisions

- Keep Next.js, React and vanilla CSS. No component framework migration.
- Use warm monochrome CSS variables, flat surfaces and one muted green accent.
- Self-host Geist, Geist Mono and Newsreader through font packages. No external font requests.
- Use the serif only for the page and proposal headings. Numeric conditions use tabular monospace.
- Group controls by rail, state/timing, operating limits and campaign selection.
- Show requested conditions in one comparison table. Display observations once below it.
- Preserve draft and current step in this tab's session storage; do not persist proposals as measurements.
- Use the explicit OLED example action. Firmware/fixture identities and example limits remain pending review; the timing values are preview placeholders.
- Keep the table scrollable on phones, with a visible hint and keyboard focus.
- Use only opacity/transform motion and honor reduced motion.

## Preflight

Reviewed before implementation; applicable items verified in source and browser:

- [x] Existing framework inspected
- [x] Existing dependencies inspected
- [x] Existing styles and tokens inspected
- [x] Existing form flow inspected
- [x] Existing API behavior retained
- [x] HLD ownership retained
- [x] OLED example sourced from project docs
- [x] Hidden fault trigger excluded
- [x] Pending firmware marked
- [x] Pending fixture marked
- [x] Provisional timing marked
- [x] Requested/measured distinction retained
- [x] No invented results
- [x] No hardware authority implied
- [x] Warm neutral palette
- [x] One restrained accent
- [x] No gradients
- [x] No oversaturated sections
- [x] No heavy shadows
- [x] No glass effects
- [x] No decorative card grid
- [x] Small corner radii
- [x] Consistent surface language
- [x] Deliberate macro whitespace
- [x] Constrained content width
- [x] Asymmetric desktop columns
- [x] Responsive step navigation
- [x] Explicit mobile table overflow
- [x] No page overflow
- [x] Sentence-case copy
- [x] No marketing clichés
- [x] No em-dash UI copy
- [x] No emoji decoration
- [x] Local font assets
- [x] Editorial heading contrast
- [x] Monospace numeric values
- [x] Subtle medium font weights
- [x] Full review text retained
- [x] No ellipsis or line clamps
- [x] Semantic landmarks
- [x] Labeled fields
- [x] Hint descriptions linked
- [x] Fieldset groups
- [x] Proper table headers and caption
- [x] Active step exposed
- [x] Future steps disabled
- [x] Skip link
- [x] Keyboard focus rings
- [x] Step-change focus
- [x] Inline errors
- [x] Loading placeholder
- [x] Empty-results state
- [x] Button hover feedback
- [x] Button pressed feedback
- [x] Reduced-motion support
- [x] Transform/opacity animations only
- [x] No fixed viewport height
- [x] Draft restoration
- [x] Branded favicon
- [x] Production build and browser review
