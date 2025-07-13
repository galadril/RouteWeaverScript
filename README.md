# 🗺️ RouteWeaver

<div align="center">

**Transform your photos into interactive travel maps and routes**

[![Python](https://img.shields.io/badge/Python-3.6%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![GPS](https://img.shields.io/badge/GPS-Enabled-orange?style=for-the-badge&logo=location&logoColor=white)](https://github.com/yourusername/RouteWeaver)

*Rediscover your travel history • Organize photos geographically • Create custom travel routes*

</div>

---

## ✨ What is RouteWeaver?

RouteWeaver is a powerful photo-based trip reconstruction and route creation tool that extracts GPS data from your photos to recreate your travel adventures. Whether you're organizing years of travel photos or planning your next adventure, RouteWeaver transforms your memories into interactive maps and exportable routes.

## 🚀 Key Features

<table>
<tr>
<td width="33%" align="center">
<h3>📸 Photo Magic</h3>
<b>Smart GPS Extraction</b><br>
Extract location data from photos<br>
<b>Intelligent Inference</b><br>
Add locations to non-GPS photos<br>
<b>Timeline Recreation</b><br>
Reconstruct your journey chronologically
</td>
<td width="33%" align="center">
<h3>🗺️ Route Creation</h3>
<b>Custom Routes</b><br>
Define routes with specific addresses<br>
<b>Interactive Maps</b><br>
Generate beautiful HTML visualizations<br>
<b>GPX Export</b><br>
Compatible with navigation apps
</td>
<td width="33%" align="center">
<h3>⚡ Advanced Processing</h3>
<b>Batch Processing</b><br>
Handle entire photo libraries<br>
<b>Multiple Data Sources</b><br>
Import GPX files and photo metadata<br>
<b>Timeline Animation</b><br>
Visualize journey progression
</td>
</tr>
</table>

## 🛠️ Quick Setup
# 📂 Clone the repository
git clone https://github.com/galadril/RouteWeaverScript.git 
cd RouteWeaverScript

# 🐍 Install dependencies
pip install -r requirements.txt

# 🎯 Basic usage
python main.py /path/to/photos
## 💡 Usage Examples

<details>
<summary><b>📸 Photo Processing</b></summary>
# Basic photo processing
python main.py "C:\Photos\2023-Europe-Trip"

# Enhanced processing with all features
python main.py "C:\Photos\2023-Europe-Trip" --infer --filename-dates --advanced-map --geocode

# Custom output files
python main.py "C:\Photos\Trip" "custom.gpx" "summary.md" "data.csv" "map.html"
</details>

<details>
<summary><b>🌍 Custom Route Creation</b></summary>
# Simple city-to-city route
python main.py --route-cities "London, UK" "Paris, France" "Amsterdam, Netherlands"

# Route with specific dates
python main.py --route-cities "Tokyo, Japan" "Kyoto, Japan" "Osaka, Japan" \
  --route-dates 2024-03-15 2024-03-18 2024-03-21

# USA West Coast adventure
python main.py --route-cities "San Francisco, CA" "Yosemite National Park" "Las Vegas, NV" \
  --route-dates 2024-05-12 2024-05-15 2024-05-18 \
  --route-gpx-output "west_coast.gpx" --route-html-output "west_coast.html"
</details>

<details>
<summary><b>📍 Custom Locations</b></summary>

Create a `custom_locations.json` file:{
  "Monument Valley Tribal Park": [37.0042, -110.1129],
  "Secret Beach, Kauai": [22.2171, -159.3686],
  "My Favorite Restaurant": [40.7589, -73.9851]
}# Use custom locations in routes
python main.py --route-cities "San Francisco, CA" "Monument Valley Tribal Park" \
  --custom-locations-file custom_locations.json
</details>

<details>
<summary><b>📁 Batch & Multi-Folder Processing</b></summary>
# Process multiple folders
python main.py --multi-folders "C:\Photos\Trip1" "C:\Photos\Trip2" --infer

# Batch process entire photo library
python main.py --batch "C:\Photos" --batch-output "TripArchive" --infer --filename-dates

# Advanced batch processing with geocoding
python main.py --batch "C:\Photos" --geocode --skip-preview
</details>

<details>
<summary><b>🛰️ GPX Integration</b></summary>
# Import existing GPX file
python main.py "C:\Photos\Hiking-Trip" --gpx-import "route.gpx" --infer

# Search for GPX files in directories
python main.py "C:\Photos\GPS-Logs" --gpx-search "C:\GPS-Data" "C:\Downloads\GPX"

# Treat GPX as single route (no clustering)
python main.py "C:\Photos\Road-Trip" --gpx-import "route.gpx" --gpx-as-route
</details>

<details>
<summary><b>🌟 Real-World Adventures</b></summary>

**🏞️ USA National Parks Road Trip**python main.py --route-cities "Denver, CO" "Rocky Mountain National Park" \
  "Arches National Park, UT" "Zion National Park, UT" "Grand Canyon, AZ" \
  --route-dates 2024-07-01 2024-07-03 2024-07-05 2024-07-07 2024-07-09
**🏰 European City Tour**python main.py --route-cities "London, UK" "Brussels, Belgium" "Amsterdam, Netherlands" \
  "Berlin, Germany" "Prague, Czech Republic" "Vienna, Austria" \
  --route-start-date 2024-09-01
**🏝️ Southeast Asian Adventure**python main.py --route-cities "Bangkok, Thailand" "Chiang Mai, Thailand" \
  "Hanoi, Vietnam" "Siem Reap, Cambodia" --route-gpx-output "asia_trip.gpx"
</details>

## ⚙️ Command Reference

| 🎯 **Core Options** | Description |
|---------------------|-------------|
| `--infer` | 🧠 Infer locations for photos without GPS data |
| `--filename-dates` | 📅 Extract dates from filenames when EXIF is missing |
| `--advanced-map` | 🗺️ Create interactive HTML map with timeline |
| `--geocode` | 🌍 Reverse geocode locations (adds place names) |
| `--skip-preview` | ⚡ Skip interactive preview for automation |

| 📂 **Input Sources** | Description |
|----------------------|-------------|
| `--multi-folders` | 📁 Process multiple photo folders |
| `--gpx-import` | 🛰️ Import GPX file as reference track |
| `--gpx-search` | 🔍 Search directories for GPX files |
| `--batch` | 📚 Batch process folders under root directory |

| 🎨 **Customization** | Description |
|----------------------|-------------|
| `--gap` | ⏰ Time gap in hours for clustering (default: 4) |
| `--distance` | 📏 Distance gap in km for clustering (default: 25) |
| `--tz-shift` | 🌍 Timezone shift in hours |
| `--date-range` | 📅 Filter photos by date range |
| `--min-photos` | 📸 Minimum photos needed for trip (default: 3) |

## 📤 Output Files

All files are saved in a `Route` subfolder within your photo directory:

| File Type | Icon | Description |
|-----------|------|-------------|
| **GPX** | 🛰️ | Standard GPS format for navigation apps |
| **HTML** | 🗺️ | Interactive map with timeline and clustering |
| **Markdown** | 📝 | Human-readable trip summary |
| **CSV** | 📊 | Data export for services like Polarsteps |

## 💎 Pro Tips

> **🎯 For accurate routes**: Include as many geotagged photos as possible
> 
> **🗺️ For custom routes**: Use specific addresses for better geocoding
> 
> **📸 For photo inference**: Ensure photo timestamps are accurate
> 
> **📁 For batch processing**: Organize photos in folders by trip
> 
> **⚡ For large collections**: Use `--skip-preview` for automation
> 
> **📍 For hard-to-find places**: Create custom_locations.json with exact coordinates
> 
> **🌍 For timezone issues**: Use `--tz-shift` to adjust timestamps
> 
> **📅 For old photos**: Use `--filename-dates` to extract dates from filenames

## 🔧 Requirements

- **Python 3.6+**
- **Dependencies**: `piexif` • `gpxpy` • `geopy` • `folium` • `haversine` • `Pillow`

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Feel free to submit a Pull Request.

---

<div align="center">

**Made with ❤️ for travelers and photographers**

⭐ Star this repo if you found it helpful!

</div>
