// Shinagawa, for the Namboku line extension's terminus. It is not in the
// subway station query: today it is a JR and Keikyu station with no subway
// platform, and the Namboku branch under construction has no OSM node yet.
// The new platform will be under the station's west side, so the existing
// station node is the position this board uses.
[out:json][timeout:60];
node["railway"="station"]["name:en"="Shinagawa"](35.61,139.72,35.64,139.75);
out body;
