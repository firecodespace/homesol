# homesol

Rooftop solar planning for Indian homes: outline your roof on a satellite map, mark what shades it, and see where panels will actually get sun.

## Run

```bash
cd web
pnpm install
pnpm dev
```

`pnpm test` runs the sun-position and shading unit tests.

## How shading is worked out

- **Height from satellite shadows** (`web/src/lib/solar/shadowHeight.ts`): click the foot of a neighbouring building and the tip of its shadow. The satellite image's capture date comes from Esri's imagery metadata; the capture time is solved from the shadow's direction, which fixes the sun's elevation and so the height.
- **Yearly sun map** (`web/src/lib/solar/shading.ts`): each obstruction is treated as a vertical prism and the roof is sampled on a grid against half-hourly sun positions for the 21st of every month.
