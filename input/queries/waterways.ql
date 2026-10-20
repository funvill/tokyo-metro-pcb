// River and canal centre lines, to carry the narrow waterways the polygons
// miss. The Kanda river and the Imperial Palace moats are both narrow
// enough that OSM maps parts of them as a line rather than an area.
[out:json][timeout:600];
(
  way["waterway"~"^(river|canal)$"](35.40,139.50,35.92,140.10);
  way["waterway"="stream"]["name"](35.40,139.50,35.92,140.10);
);
out body geom;
