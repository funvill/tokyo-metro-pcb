// Stations and alignments under construction or proposed, in case OSM
// already carries any of the three new stations (Edagawa and Sengoku on the
// Yurakucho branch, Shinagawa on the Namboku branch). Anything missing is
// hand-placed in future_stations.json with its source recorded (lesson A3).
[out:json][timeout:300];
(
  node["railway"~"^(construction|proposed)$"]["name"](35.50,139.55,35.86,140.03);
  node["construction:railway"="station"](35.50,139.55,35.86,140.03);
  node["proposed:railway"="station"](35.50,139.55,35.86,140.03);
  way["railway"="construction"](35.50,139.55,35.86,140.03);
  way["railway"="proposed"]["proposed"="subway"](35.50,139.55,35.86,140.03);
);
out body geom;
