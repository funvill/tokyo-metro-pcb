// Canonical station nodes: one per station per operator, with name,
// name:en and the station codes in railway:ref. Interchanges are tagged
// more than once, so these still need de-duplicating by position.
[out:json][timeout:300];
(
  node["railway"~"^(station|halt)$"]["station"="subway"](35.50,139.55,35.86,140.03);
  node["railway"~"^(station|halt)$"]["subway"="yes"](35.50,139.55,35.86,140.03);
  node["public_transport"="station"]["subway"="yes"](35.50,139.55,35.86,140.03);
);
out body;
