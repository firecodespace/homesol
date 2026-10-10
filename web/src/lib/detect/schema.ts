import { z } from "zod";

const Point = z.object({ x: z.number(), y: z.number() });

/** What the vision model reports for one object. Coordinates are image pixels, origin top-left. */
export const DetectedObstruction = z.object({
  kind: z.enum(["building", "tree", "tank", "other"]),
  label: z.string().describe("Two to five plain words, e.g. 'stair room' or 'neighbour to the south'."),
  on_roof: z.boolean().describe("True if the object stands on the outlined roof itself."),
  outline: z.array(Point).describe("Footprint corners in order, 3 to 8 points."),
  shadow: z
    .object({
      base: Point.describe("Foot of the corner casting the shadow, on the surface the shadow falls on."),
      tip: Point.describe("Where that same corner's shadow ends."),
    })
    .nullable()
    .describe("Only when a clear shadow of this object is visible end to end; otherwise null."),
  typical_height_m: z.number().describe("Best guess of height above the surface it stands on, from its type and size."),
});

export const Detection = z.object({ obstructions: z.array(DetectedObstruction) });
export type Detection = z.infer<typeof Detection>;

export const DetectRequest = z.object({
  /** Base64 JPEG, square, with the roof outlined in yellow. */
  image: z.string().min(100),
  size: z.number().int().positive(),
  metresPerPixel: z.number().positive(),
  /** Compass bearing shadows point in at the likely capture time, if the image date is known. */
  shadowBearing: z.number().nullable(),
});
export type DetectRequest = z.infer<typeof DetectRequest>;
