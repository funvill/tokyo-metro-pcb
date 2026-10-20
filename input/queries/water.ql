// Water as polygons, not coastline lines: assembling lines into land/sea
// faces is where the Vancouver OSM attempt silently lost an island and a
// whole estuary (lesson B1). Tokyo Bay is tagged as coastline, so both are
// needed. `out body geom` is required — `out tags geom` drops relation
// members and multipolygon water vanishes (lesson A3).
//
// The box is wider than the station box: Tokyo Bay, the Arakawa and the
// Edogawa all run off the edges of the network.
[out:json][timeout:600];
(
  way["natural"="water"](35.40,139.50,35.92,140.10);
  rel["natural"="water"](35.40,139.50,35.92,140.10);
  way["waterway"="riverbank"](35.40,139.50,35.92,140.10);
  rel["waterway"="riverbank"](35.40,139.50,35.92,140.10);
  way["natural"="coastline"](35.40,139.50,35.92,140.10);
);
out body geom;
