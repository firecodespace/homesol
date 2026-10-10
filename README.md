# homesol

Rooftop solar planning for Indian homes: outline your roof on a satellite map, mark what shades it, and see where panels will actually get sun.

## Run

```bash
cd web
pnpm install
pnpm dev
```

`pnpm test` runs the sun-position, shading, skyline and sizing unit tests.

The rooftop skyline scan reads the phone's compass and tilt sensors, which browsers only expose over HTTPS. To try it on a phone on the same Wi-Fi, run `pnpm dev:https` and open `https://<your-computer's-ip>:3000` (accept the self-signed certificate warning).

## How shading is worked out

- **Height from satellite shadows** (`web/src/lib/solar/shadowHeight.ts`): click the foot of a neighbouring building and the tip of its shadow. The satellite image's capture date comes from Esri's imagery metadata; the capture time is solved from the shadow's direction, which fixes the sun's elevation and so the height.
- **Yearly sun map** (`web/src/lib/solar/shading.ts`): each obstruction is treated as a vertical prism and the roof is sampled on a grid against half-hourly sun positions for the 21st of every month.
- **Rooftop skyline scan** (`web/src/lib/solar/horizon.ts`): standing on the roof, trace the tops of surrounding obstructions with the phone camera. Compass bearing and tilt become a skyline profile; the roof is shaded whenever the sun is below it.
- **System sizing** (`web/src/lib/solar/sizing.ts`): monthly sunlight from NASA POWER's 25-year climatology, a 75% performance ratio and the roof's solar access give expected units per kW; the system is sized to the yearly bill or the roof, whichever is smaller.
