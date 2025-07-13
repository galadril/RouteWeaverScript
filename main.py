import os
import argparse
import piexif
import gpxpy
import gpxpy.gpx
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
import time
import math
import csv
from haversine import haversine
import folium
import re
from PIL import Image, ExifTags
import json
from collections import defaultdict
import glob
from dateutil import parser as date_parser
import concurrent.futures
from pathlib import Path
import shutil
from folium.plugins import MarkerCluster, HeatMap, TimestampedGeoJson

def extract_exif(filepath, tz_shift=0):
    try:
        exif_dict = piexif.load(filepath)
        gps = exif_dict.get("GPS", {})
        dt = exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        if dt:
            timestamp = datetime.strptime(dt.decode(), '%Y:%m:%d %H:%M:%S') + timedelta(hours=tz_shift)
        else:
            timestamp = None

        if gps:
            lat = convert_gps_coord(gps.get(piexif.GPSIFD.GPSLatitude), gps.get(piexif.GPSIFD.GPSLatitudeRef))
            lon = convert_gps_coord(gps.get(piexif.GPSIFD.GPSLongitude), gps.get(piexif.GPSIFD.GPSLongitudeRef))
            alt = convert_altitude(gps.get(piexif.GPSIFD.GPSAltitude))
            return timestamp, lat, lon, alt, filepath
        else:
            return timestamp, None, None, None, filepath
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None, None, None, None, filepath

def extract_timestamp_from_filename(filepath):
    """Try to extract timestamp from filename using common patterns"""
    filename = os.path.basename(filepath)
    
    # Common patterns for timestamps in filenames
    patterns = [
        # IMG_YYYYMMDD_HHMMSS
        r'IMG_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})',
        # YYYY-MM-DD_HH-MM-SS
        r'(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})',
        # YYYYMMDD_HHMMSS
        r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})',
        # IMG-YYYYMMDD-HHMMSS
        r'IMG-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})',
        # WhatsApp Image YYYY-MM-DD at HH.MM.SS
        r'WhatsApp Image (\d{4})-(\d{2})-(\d{2}) at (\d{2})\.(\d{2})\.(\d{2})',
        # Photo YYYY-MM-DD HH-MM-SS
        r'Photo (\d{4})-(\d{2})-(\d{2}) (\d{2})-(\d{2})-(\d{2})',
        # YYYYMMDD_HHMMSS_XXX (with some suffix)
        r'^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_\w+',
        # New: Simple year pattern to at least get year-based organization
        r'(\d{4})[_-]',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            groups = match.groups()
            if len(groups) == 6:  # Year, Month, Day, Hour, Minute, Second
                try:
                    year = int(groups[0])
                    month = int(groups[1])
                    day = int(groups[2])
                    hour = int(groups[3])
                    minute = int(groups[4])
                    second = int(groups[5])
                    
                    return datetime(year, month, day, hour, minute, second)
                except (ValueError, TypeError):
                    continue
            elif len(groups) == 1:  # Just year
                try:
                    year = int(groups[0])
                    # Use January 1st as default date if only year is available
                    return datetime(year, 1, 1, 12, 0, 0)
                except (ValueError, TypeError):
                    continue
    
    # Fallback to file modification time
    return datetime.fromtimestamp(os.path.getmtime(filepath))

def extract_timestamp_from_metadata(filepath):
    """Try to extract timestamp from file metadata using PIL"""
    try:
        # Try to get the DateTimeOriginal or other date fields from image metadata
        img = Image.open(filepath)
        img_exif = img._getexif()
        
        if img_exif:
            for tag_id, value in img_exif.items():
                tag_name = ExifTags.TAGS.get(tag_id, '')
                if tag_name in ['DateTimeOriginal', 'DateTime', 'DateTimeDigitized']:
                    return datetime.strptime(value, '%Y:%m:%d %H:%M:%S')
        
        # If no EXIF timestamp found, check file creation/modification time
        return datetime.fromtimestamp(os.path.getmtime(filepath))
    except Exception:
        # Fallback to file modification time if PIL fails
        return datetime.fromtimestamp(os.path.getmtime(filepath))

def convert_gps_coord(coord, ref):
    if not coord or not ref:
        return None
    d, m, s = coord
    val = d[0]/d[1] + m[0]/m[1]/60 + s[0]/s[1]/3600
    if ref in [b'S', b'W']:
        val = -val
    return val

def convert_altitude(alt):
    if not alt:
        return None
    return alt[0] / alt[1]

def extract_location_from_path(filepath):
    """Try to extract location from the file path or parent folder names"""
    # Split the path to analyze folder structure
    path_parts = filepath.split(os.sep)
    
    # Ignore common folder names and look for potential location info
    common_folders = ['pictures', 'photos', 'images', 'camera', 'dcim', 'iphone', 'android', 'backup', 'desktop']
    potential_location_folders = []
    
    for part in path_parts:
        # Strip common prefixes like '2023_', 'Vacation_', etc.
        cleaned = re.sub(r'^\d{4}_|^\d{2}_\d{2}_|^Vacation_|^Trip_', '', part, flags=re.IGNORECASE)
        
        # Skip common folder names or short names (likely not locations)
        if cleaned.lower() not in common_folders and len(cleaned) > 3:
            potential_location_folders.append(cleaned)
    
    # Return the most specific folder (closest to the file) that likely represents a location
    if potential_location_folders:
        return potential_location_folders[-1].replace('_', ' ')
    
    return None

def load_location_cache(folder):
    """Load cached location data if available"""
    cache_file = os.path.join(folder, 'Route', 'location_cache.json')
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading location cache: {e}")
    
    return {}

def save_location_cache(folder, cache):
    """Save location data to cache file"""
    route_folder = ensure_route_folder(folder)
    cache_file = os.path.join(route_folder, 'location_cache.json')
    
    try:
        with open(cache_file, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Error saving location cache: {e}")

def geocode_location_name(location_name):
    """Convert a location name to coordinates using Nominatim"""
    if not location_name:
        return None, None
        
    geolocator = Nominatim(user_agent="photo-trip-scheduler")
    try:
        location = geolocator.geocode(location_name)
        if location:
            return location.latitude, location.longitude
        return None, None
    except Exception as e:
        print(f"Geocoding error: {e}")
        return None, None

def load_gpx_tracks(gpx_file):
    """Load track points from an existing GPX file"""
    try:
        with open(gpx_file, 'r') as f:
            gpx = gpxpy.parse(f)
        
        points = []
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    # Convert to the same format as photo data
                    points.append((point.time, point.latitude, point.longitude, point.elevation, None))
        
        return sorted(points, key=lambda x: x[0]) if points and points[0][0] else points
    except Exception as e:
        print(f"Error loading GPX file {gpx_file}: {e}")
        return []

def scan_photos(folder, tz_shift=0, infer_locations=False, use_filename_dates=False, date_range=None):
    """Scan folder for photos with or without GPS data"""
    gps_photos = []
    non_gps_photos = []
    location_cache = load_location_cache(folder) if infer_locations else {}

    print("Scanning for photos...")
    for root, dirs, files in os.walk(folder):
        for file in files:
            if file.lower().endswith(('jpg', 'jpeg')):
                full_path = os.path.join(root, file)
                
                # Try to extract EXIF data first
                timestamp, lat, lon, alt, path = extract_exif(full_path, tz_shift)
                
                # If no timestamp, try alternative methods
                if not timestamp:
                    if use_filename_dates:
                        timestamp = extract_timestamp_from_filename(full_path)
                    else:
                        timestamp = extract_timestamp_from_metadata(full_path)
                
                # If we have a timestamp, check date range filter
                if timestamp:
                    # Filter by date range if specified
                    if date_range:
                        start_date, end_date = date_range
                        if timestamp.date() < start_date or timestamp.date() > end_date:
                            continue
                    
                    # Separate photos with and without GPS data
                    if lat and lon:
                        gps_photos.append((timestamp, lat, lon, alt, full_path))
                    else:
                        non_gps_photos.append((timestamp, None, None, None, full_path))
    
    # Sort both lists by timestamp
    gps_photos = sorted(gps_photos, key=lambda x: x[0])
    non_gps_photos = sorted(non_gps_photos, key=lambda x: x[0])
    
    return gps_photos, non_gps_photos, location_cache

def scan_multiple_folders(folders, tz_shift=0, infer_locations=False, use_filename_dates=False, date_range=None):
    """Scan multiple folders for photos and merge the results"""
    all_gps_photos = []
    all_non_gps_photos = []
    
    for folder in folders:
        print(f"\nScanning folder: {folder}")
        gps_photos, non_gps_photos, _ = scan_photos(folder, tz_shift, infer_locations, use_filename_dates, date_range)
        all_gps_photos.extend(gps_photos)
        all_non_gps_photos.extend(non_gps_photos)
    
    # Re-sort the merged lists
    all_gps_photos = sorted(all_gps_photos, key=lambda x: x[0])
    all_non_gps_photos = sorted(all_non_gps_photos, key=lambda x: x[0])
    
    return all_gps_photos, all_non_gps_photos

def infer_coordinates(non_gps_photos, gps_photos, location_cache, folder):
    """Infer coordinates for photos without GPS data"""
    enriched_photos = []
    updated_cache = location_cache.copy()
    
    # If there are GPS photos, we can use them for interpolation
    if gps_photos:
        print(f"\nInferring locations for {len(non_gps_photos)} photos without GPS data using existing GPS photos...")
        
        # Create a timeline of known positions
        gps_timeline = [(photo[0], (photo[1], photo[2])) for photo in gps_photos]
        
        for timestamp, _, _, _, filepath in non_gps_photos:
            # Find the closest GPS photos in time - before and after
            before = None
            after = None
            
            for gps_time, gps_coords in gps_timeline:
                if gps_time <= timestamp and (before is None or gps_time > before[0]):
                    before = (gps_time, gps_coords)
                if gps_time >= timestamp and (after is None or gps_time < after[0]):
                    after = (gps_time, gps_coords)
            
            # Infer location
            lat = None
            lon = None
            
            # Case 1: We have positions both before and after
            if before and after:
                # Linear interpolation between two points
                time_range = (after[0] - before[0]).total_seconds()
                time_delta = (timestamp - before[0]).total_seconds()
                ratio = time_delta / time_range
                
                lat = before[1][0] + ratio * (after[1][0] - before[1][0])
                lon = before[1][1] + ratio * (after[1][1] - before[1][1])
            
            # Case 2: We only have a position before
            elif before:
                lat, lon = before[1]
            
            # Case 3: We only have a position after
            elif after:
                lat, lon = after[1]
            
            # Add to enriched photos
            if lat and lon:
                enriched_photos.append((timestamp, lat, lon, None, filepath))
                # Add to cache by path relative to folder
                rel_path = os.path.relpath(filepath, folder)
                updated_cache[rel_path] = {"lat": lat, "lon": lon}
    
    # Handle remaining photos by trying to extract location from folder names
    remaining = [p for p in non_gps_photos if p[4] not in [e[4] for e in enriched_photos]]
    
    if remaining:
        print(f"Trying to extract locations from folder names for {len(remaining)} remaining photos...")
        
        # Group by folder for more efficient geocoding
        by_folder = defaultdict(list)
        for photo in remaining:
            folder_path = os.path.dirname(photo[4])
            by_folder[folder_path].append(photo)
        
        for folder_path, folder_photos in by_folder.items():
            location_name = extract_location_from_path(folder_path)
            
            # Check if we already have this location in our cache
            folder_key = os.path.relpath(folder_path, folder)
            if folder_key in updated_cache:
                lat, lon = updated_cache[folder_key]["lat"], updated_cache[folder_key]["lon"]
            else:
                lat, lon = geocode_location_name(location_name)
                if lat and lon:
                    updated_cache[folder_key] = {"lat": lat, "lon": lon}
                    time.sleep(1)  # Avoid overloading geocoding service
            
            # If we found coordinates, apply to all photos in this folder
            if lat and lon:
                for timestamp, _, _, _, filepath in folder_photos:
                    enriched_photos.append((timestamp, lat, lon, None, filepath))
                    rel_path = os.path.relpath(filepath, folder)
                    updated_cache[rel_path] = {"lat": lat, "lon": lon}
    
    # Save updated cache
    save_location_cache(folder, updated_cache)
    
    return enriched_photos

def cluster_photos(photos, time_gap_hours=4, distance_km=25):
    """Group photos into clusters based on time and distance gaps"""
    if not photos:
        return []
        
    clusters = []
    current_cluster = []
    last_time = None
    last_coord = None
    gap = timedelta(hours=time_gap_hours)

    for photo in photos:
        ts, lat, lon, alt, path = photo
        coord = (lat, lon)
        time_condition = not last_time or ts - last_time <= gap
        distance_condition = not last_coord or haversine(coord, last_coord) <= distance_km

        if time_condition and distance_condition:
            current_cluster.append(photo)
        else:
            clusters.append(current_cluster)
            current_cluster = [photo]
        last_time = ts
        last_coord = coord

    if current_cluster:
        clusters.append(current_cluster)

    return clusters

def interactive_preview(clusters):
    print("\nTrip Clustering Preview:\n")
    for idx, cluster in enumerate(clusters):
        start = cluster[0][0].strftime("%Y-%m-%d %H:%M")
        end = cluster[-1][0].strftime("%Y-%m-%d %H:%M")
        sample_lat = cluster[0][1]
        sample_lon = cluster[0][2]
        print(f"Segment {idx+1}: {len(cluster)} photos from {start} to {end} (start: {sample_lat:.5f}, {sample_lon:.5f})")

    proceed = input("\nProceed with file generation? (y/n): ").lower()
    return proceed == 'y'

def interactive_location_input(non_gps_photos, folder):
    """Allow manual input of locations for photos without GPS data"""
    enriched_photos = []
    grouped_photos = defaultdict(list)
    location_cache = {}
    
    # Group photos by parent folder for easier input
    for photo in non_gps_photos:
        parent_folder = os.path.basename(os.path.dirname(photo[4]))
        grouped_photos[parent_folder].append(photo)
    
    print(f"\nFound {len(non_gps_photos)} photos without GPS data grouped in {len(grouped_photos)} folders.")
    print("You can manually enter locations for groups of photos.")
    
    for folder_name, photos in grouped_photos.items():
        sample_path = photos[0][4]
        date_range = f"{photos[0][0].strftime('%Y-%m-%d')} to {photos[-1][0].strftime('%Y-%m-%d')}"
        
        print(f"\nFolder: {folder_name}")
        print(f"Contains {len(photos)} photos from {date_range}")
        print(f"Example: {os.path.basename(sample_path)}")
        
        location = input("Enter location (city, country) or press Enter to skip: ")
        
        if location.strip():
            lat, lon = geocode_location_name(location)
            
            if lat and lon:
                print(f"Found coordinates: {lat:.5f}, {lon:.5f}")
                
                # Apply to all photos in this folder
                for timestamp, _, _, _, filepath in photos:
                    enriched_photos.append((timestamp, lat, lon, None, filepath))
                    # Save to cache
                    rel_path = os.path.relpath(filepath, folder)
                    location_cache[rel_path] = {"lat": lat, "lon": lon}
            else:
                print("Could not geocode this location. Skipping...")
        else:
            print("Skipping this folder...")
    
    # Save location cache
    save_location_cache(folder, location_cache)
    
    return enriched_photos

def create_gpx(clusters, output_file):
    gpx = gpxpy.gpx.GPX()

    for idx, cluster in enumerate(clusters):
        track = gpxpy.gpx.GPXTrack(name=f"Segment {idx+1}")
        gpx.tracks.append(track)
        segment = gpxpy.gpx.GPXTrackSegment()
        track.segments.append(segment)

        for ts, lat, lon, alt, path in cluster:
            point = gpxpy.gpx.GPXTrackPoint(lat, lon, elevation=alt, time=ts)
            segment.points.append(point)

    with open(output_file, 'w') as f:
        f.write(gpx.to_xml())

def reverse_geocode(photos):
    geolocator = Nominatim(user_agent="photo-trip-scheduler")
    enriched = []
    for ts, lat, lon, alt, path in photos:
        location = geolocator.reverse((lat, lon), language='en', timeout=10)
        address = location.address if location else "Unknown"
        enriched.append((ts, lat, lon, alt, path, address))
        time.sleep(1)
    return enriched

def write_summary(clusters, output_file, geocode=False):
    with open(output_file, 'w') as f:
        f.write("# Trip Summary\n\n")
        geolocator = Nominatim(user_agent="photo-trip-scheduler") if geocode else None
        for idx, cluster in enumerate(clusters):
            start_date = cluster[0][0].strftime("%Y-%m-%d")
            f.write(f"## Segment {idx+1} - {start_date}\n")
            for ts, lat, lon, alt, path in cluster:
                address = ""
                if geolocator:
                    location = geolocator.reverse((lat, lon), language='en', timeout=10)
                    address = location.address if location else "Unknown"
                    time.sleep(1)
                elev_str = f" [{alt:.1f}m]" if alt else ""
                f.write(f"- {ts.strftime('%H:%M')} @ ({lat:.5f},{lon:.5f}){elev_str} {address}\n")
            f.write("\n")

def export_csv(clusters, output_file, geocode=False):
    geolocator = Nominatim(user_agent="photo-trip-scheduler") if geocode else None
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['Timestamp', 'Title', 'Latitude', 'Longitude', 'Altitude', 'Filename', 'Address']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for idx, cluster in enumerate(clusters):
            for ts, lat, lon, alt, path in cluster:
                address = ""
                if geolocator:
                    location = geolocator.reverse((lat, lon), language='en', timeout=10)
                    address = location.address if location else "Unknown"
                    time.sleep(1)
                # Get just the filename without the full path
                filename = os.path.basename(path) if path else "GPX Point"
                writer.writerow({
                    'Timestamp': ts.strftime('%Y-%m-%d %H:%M:%S'),
                    'Title': f'Segment {idx+1}',
                    'Latitude': lat,
                    'Longitude': lon,
                    'Altitude': alt if alt else '',
                    'Filename': filename,
                    'Address': address
                })

def export_map(clusters, output_file):
    if not clusters:
        print("No data to generate map.")
        return
        
    start_lat, start_lon = clusters[0][0][1], clusters[0][0][2]
    m = folium.Map(location=[start_lat, start_lon], zoom_start=6)

    for idx, cluster in enumerate(clusters):
        color = ["red", "blue", "green", "orange", "purple", "darkred", "cadetblue"] [idx % 7]
        points = [(lat, lon) for ts, lat, lon, alt, path in cluster]
        folium.PolyLine(points, color=color, weight=2.5, opacity=0.8).add_to(m)
        
        # Add markers with popup showing filename for each point
        for ts, lat, lon, alt, path in cluster:
            filename = os.path.basename(path) if path else "GPX Point"
            popup_text = f"{filename}<br>{ts.strftime('%Y-%m-%d %H:%M')}"
            folium.CircleMarker(
                [lat, lon], 
                radius=3, 
                color=color, 
                fill=True,
                popup=popup_text
            ).add_to(m)

    m.save(output_file)

def export_advanced_map(clusters, output_file, include_heatmap=True, include_timeline=True):
    """Create an advanced interactive map with additional features"""
    if not clusters:
        print("No data to generate map.")
        return
        
    # Calculate center point of all photos
    all_lats = []
    all_lons = []
    for cluster in clusters:
        for _, lat, lon, _, _ in cluster:
            all_lats.append(lat)
            all_lons.append(lon)
    
    center_lat = sum(all_lats) / len(all_lats)
    center_lon = sum(all_lons) / len(all_lons)
    
    # Create base map
    m = folium.Map(location=[center_lat, center_lon], zoom_start=5)
    
    # Add cluster tracks
    for idx, cluster in enumerate(clusters):
        color = ["red", "blue", "green", "orange", "purple", "darkred", "cadetblue"][idx % 7]
        
        # Get start and end dates for naming
        start_date = cluster[0][0].strftime("%Y-%m-%d")
        end_date = cluster[-1][0].strftime("%Y-%m-%d")
        track_name = f"Trip {idx+1}: {start_date}"
        if start_date != end_date:
            track_name += f" to {end_date}"
            
        # Create track line
        points = [(lat, lon) for _, lat, lon, _, _ in cluster]
        folium.PolyLine(
            points, 
            color=color, 
            weight=3.0, 
            opacity=0.8,
            tooltip=track_name
        ).add_to(m)
        
        # Add marker clusters for photos
        marker_cluster = MarkerCluster(name=f"Photos - {track_name}").add_to(m)
        
        for ts, lat, lon, alt, path in cluster:
            filename = os.path.basename(path) if path else "GPX Point"
            popup_html = f"""
            <div>
                <p><strong>Date:</strong> {ts.strftime('%Y-%m-%d %H:%M')}</p>
                <p><strong>Coordinates:</strong> {lat:.5f}, {lon:.5f}</p>
                <p><strong>Filename:</strong> {filename}</p>
            </div>
            """
            folium.Marker(
                [lat, lon],
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=ts.strftime('%Y-%m-%d %H:%M'),
                icon=folium.Icon(color=color, icon="camera" if path else "map-pin", prefix="fa")
            ).add_to(marker_cluster)
        
        # Add starting point marker
        start = cluster[0]
        folium.Marker(
            [start[1], start[2]],
            tooltip=f"Start: {start_date}",
            icon=folium.Icon(color=color, icon="play", prefix="fa")
        ).add_to(m)
        
        # Add ending point marker
        end = cluster[-1]
        folium.Marker(
            [end[1], end[2]],
            tooltip=f"End: {end_date}",
            icon=folium.Icon(color=color, icon="stop", prefix="fa")
        ).add_to(m)
    
    # Add heatmap layer
    if include_heatmap:
        heatmap_data = []
        for cluster in clusters:
            for _, lat, lon, _, _ in cluster:
                heatmap_data.append([lat, lon, 1.0])  # weight of 1.0 for each point
        
        HeatMap(heatmap_data, name="Heatmap").add_to(m)
    
    # Add timeline if requested
    if include_timeline:
        features = []
        
        # Create GeoJSON features for timeline
        for idx, cluster in enumerate(clusters):
            color = ["red", "blue", "green", "orange", "purple", "darkred", "cadetblue"][idx % 7]
            
            for ts, lat, lon, _, _ in cluster:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [lon, lat]
                    },
                    "properties": {
                        "time": ts.strftime('%Y-%m-%d %H:%M:%S'),
                        "icon": "circle",
                        "iconstyle": {
                            "fillColor": color,
                            "fillOpacity": 0.8,
                            "stroke": "true",
                            "radius": 5
                        },
                        "style": {"weight": 0},
                        "popup": ts.strftime('%Y-%m-%d %H:%M')
                    }
                })
        
        TimestampedGeoJson({
            "type": "FeatureCollection",
            "features": features
        }, 
        period="PT1H",
        duration="PT1M",
        add_last_point=True,
        auto_play=False,
        loop=False,
        max_speed=10,
        date_options='YYYY-MM-DD HH:mm',
        time_slider_drag_update=True
        ).add_to(m)
    
    # Add layer control
    folium.LayerControl().add_to(m)
    
    # Save map
    m.save(output_file)

def ensure_route_folder(photo_folder):
    """Create a Route folder inside the photo folder if it doesn't exist already"""
    route_folder = os.path.join(photo_folder, "Route")
    if not os.path.exists(route_folder):
        os.makedirs(route_folder)
    return route_folder

def batch_process_folders(root_folder, output_folder, tz_shift=0, time_gap_hours=4, distance_km=25, 
                          infer_locations=True, use_filename_dates=True, geocode=False):
    """Process multiple folders in batch mode to discover old holiday routes"""
    # Create output folder if it doesn't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    # Find all potential photo folders
    photo_folders = []
    for entry in os.scandir(root_folder):
        if entry.is_dir() and not entry.name.startswith('.') and entry.name != output_folder:
            photo_folders.append(entry.path)
    
    print(f"Found {len(photo_folders)} folders to process")
    trips_by_year = defaultdict(list)
    all_trips = []
    
    for folder in photo_folders:
        folder_name = os.path.basename(folder)
        print(f"\nProcessing folder: {folder_name}")
        
        # Scan for photos
        gps_photos, non_gps_photos, location_cache = scan_photos(
            folder, tz_shift, infer_locations, use_filename_dates)
        
        # Enrich non-GPS photos if possible
        enriched_photos = []
        if infer_locations and non_gps_photos:
            enriched_photos = infer_coordinates(non_gps_photos, gps_photos, location_cache, folder)
        
        # Merge all photos with location data
        all_photos = sorted(gps_photos + enriched_photos, key=lambda x: x[0])
        
        if not all_photos:
            print(f"No usable photos found in {folder_name}, skipping...")
            continue
        
        # Cluster photos into trips
        clusters = cluster_photos(all_photos, time_gap_hours, distance_km)
        
        if not clusters:
            print(f"No trip clusters identified in {folder_name}, skipping...")
            continue
        
        # Process each cluster as a separate trip
        for idx, cluster in enumerate(clusters):
            start_date = cluster[0][0].date()
            end_date = cluster[-1][0].date()
            year = start_date.year
            
            # Generate a trip name
            location_names = []
            try:
                # Try to get location names for start and end
                geolocator = Nominatim(user_agent="photo-trip-scheduler")
                start_location = geolocator.reverse((cluster[0][1], cluster[0][2]), language='en')
                if start_location:
                    address_parts = start_location.address.split(',')
                    location_names.append(address_parts[-3].strip() if len(address_parts) >= 3 else address_parts[0].strip())
                
                time.sleep(1)
                
                if len(cluster) > 5:  # Only do end location for longer trips
                    end_location = geolocator.reverse((cluster[-1][1], cluster[-1][2]), language='en')
                    if end_location:
                        address_parts = end_location.address.split(',')
                        end_name = address_parts[-3].strip() if len(address_parts) >= 3 else address_parts[0].strip()
                        if end_name not in location_names:
                            location_names.append(end_name)
            except:
                # Fallback to folder name if geocoding fails
                location_names = [folder_name]
            
            # Create trip name
            if location_names:
                trip_name = f"{year}_{'-'.join(location_names)}"
            else:
                trip_name = f"{year}_{folder_name}_{start_date.strftime('%m-%d')}"
            
            # Clean up trip name to make it safe for filenames
            trip_name = re.sub(r'[<>:"/\\|?*]', '_', trip_name)
            
            # Create trip folder
            trip_folder = os.path.join(output_folder, trip_name)
            if not os.path.exists(trip_folder):
                os.makedirs(trip_folder)
            
            # Save trip files
            gpx_file = os.path.join(trip_folder, f"{trip_name}.gpx")
            md_file = os.path.join(trip_folder, f"{trip_name}.md")
            csv_file = os.path.join(trip_folder, f"{trip_name}.csv")
            html_file = os.path.join(trip_folder, f"{trip_name}.html")
            
            create_gpx([cluster], gpx_file)
            write_summary([cluster], md_file, geocode=geocode)
            export_csv([cluster], csv_file, geocode=geocode)
            export_advanced_map([cluster], html_file)
            
            # Add to trips by year
            trips_by_year[year].append({
                'name': trip_name,
                'start_date': start_date,
                'end_date': end_date,
                'photos': len(cluster),
                'folder': trip_folder,
                'gpx': gpx_file,
                'html': html_file
            })
            
            all_trips.append({
                'year': year,
                'name': trip_name,
                'start_date': start_date,
                'end_date': end_date,
                'photos': len(cluster),
                'folder': trip_folder,
                'gpx': gpx_file,
                'html': html_file
            })
            
            print(f"Created trip: {trip_name} with {len(cluster)} photos")
    
    # Create index files
    create_year_index_files(trips_by_year, output_folder)
    create_master_index_file(all_trips, output_folder)
    
    return len(all_trips)

def create_year_index_files(trips_by_year, output_folder):
    """Create index HTML files for each year"""
    for year, trips in trips_by_year.items():
        year_folder = os.path.join(output_folder, str(year))
        if not os.path.exists(year_folder):
            os.makedirs(year_folder)
        
        # Create year index.html
        index_file = os.path.join(year_folder, "index.html")
        with open(index_file, 'w') as f:
            f.write(f"""<!DOCTYPE html>
<html>
<head>
    <title>Trips from {year}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #2c3e50; }}
        .trip-list {{ display: flex; flex-wrap: wrap; }}
        .trip-card {{ 
            border: 1px solid #ddd; 
            border-radius: 8px;
            padding: 15px; 
            margin: 10px; 
            width: 300px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .trip-card h3 {{ margin-top: 0; color: #3498db; }}
        .trip-card p {{ color: #555; }}
        .trip-card a {{ 
            display: inline-block;
            background-color: #3498db;
            color: white;
            padding: 8px 12px;
            text-decoration: none;
            border-radius: 4px;
            margin-top: 10px;
            margin-right: 5px;
        }}
        .trip-card a:hover {{ background-color: #2980b9; }}
        .back-link {{ margin-bottom: 20px; }}
    </style>
</head>
<body>
    <div class="back-link">
        <a href="../index.html">? Back to all years</a>
    </div>
    <h1>Trips from {year}</h1>
    <div class="trip-list">
""")
            
            for trip in sorted(trips, key=lambda x: x['start_date']):
                rel_html = os.path.relpath(trip['html'], year_folder)
                rel_gpx = os.path.relpath(trip['gpx'], year_folder)
                f.write(f"""
        <div class="trip-card">
            <h3>{trip['name']}</h3>
            <p><strong>Dates:</strong> {trip['start_date'].strftime('%b %d')} - {trip['end_date'].strftime('%b %d, %Y')}</p>
            <p><strong>Photos:</strong> {trip['photos']}</p>
            <a href="{rel_html}" target="_blank">View Map</a>
            <a href="{rel_gpx}" download>Download GPX</a>
        </div>
""")
            
            f.write("""
    </div>
</body>
</html>
""")

def create_master_index_file(all_trips, output_folder):
    """Create a master index HTML file with all trips by year"""
    index_file = os.path.join(output_folder, "index.html")
    
    # Group trips by year
    trips_by_year = defaultdict(list)
    for trip in all_trips:
        trips_by_year[trip['year']].append(trip)
    
    # Sort years in descending order (most recent first)
    sorted_years = sorted(trips_by_year.keys(), reverse=True)
    
    with open(index_file, 'w') as f:
        f.write("""<!DOCTYPE html>
<html>
<head>
    <title>Photo Trip Explorer</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { color: #2c3e50; }
        h2 { color: #3498db; margin-top: 30px; }
        .year-section { margin-bottom: 30px; }
        .trip-list { display: flex; flex-wrap: wrap; }
        .trip-card { 
            border: 1px solid #ddd; 
            border-radius: 8px;
            padding: 15px; 
            margin: 10px; 
            width: 300px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .trip-card h3 { margin-top: 0; color: #3498db; }
        .trip-card p { color: #555; }
        .trip-card a { 
            display: inline-block;
            background-color: #3498db;
            color: white;
            padding: 8px 12px;
            text-decoration: none;
            border-radius: 4px;
            margin-top: 10px;
            margin-right: 5px;
        }
        .trip-card a:hover { background-color: #2980b9; }
        .year-link {
            display: inline-block;
            background-color: #2c3e50;
            color: white;
            padding: 10px 15px;
            text-decoration: none;
            border-radius: 4px;
            margin: 5px;
        }
        .year-link:hover { background-color: #1a252f; }
        .timeline-container {
            position: relative;
            margin: 40px 0;
            padding-left: 50px;
        }
        .timeline-line {
            position: absolute;
            left: 20px;
            top: 0;
            bottom: 0;
            width: 4px;
            background-color: #3498db;
        }
        .year-marker {
            position: absolute;
            left: 12px;
            width: 20px;
            height: 20px;
            background-color: #3498db;
            border-radius: 50%;
        }
    </style>
</head>
<body>
    <h1>Photo Trip Explorer</h1>
    
    <h2>Years</h2>
    <div>
""")

        for year in sorted_years:
            f.write(f'        <a href="#{year}" class="year-link">{year}</a>\n')
        
        f.write("""    </div>
    
    <div class="timeline-container">
        <div class="timeline-line"></div>
""")

        for year in sorted_years:
            trips = trips_by_year[year]
            f.write(f"""
        <div class="year-section" id="{year}">
            <div class="year-marker" style="top: {(sorted_years.index(year) * 300) + 50}px;"></div>
            <h2>{year}</h2>
            <p><a href="{year}/index.html">View all trips from {year}</a></p>
            <div class="trip-list">
""")

            for trip in sorted(trips, key=lambda x: x['start_date']):
                rel_html = os.path.relpath(trip['html'], output_folder)
                rel_gpx = os.path.relpath(trip['gpx'], output_folder)
                trip_name = trip['name']
                # Remove year prefix for cleaner display
                display_name = re.sub(r'^[0-9]{4}_', '', trip_name)
                
                f.write(f"""
                <div class="trip-card">
                    <h3>{display_name}</h3>
                    <p><strong>Dates:</strong> {trip['start_date'].strftime('%b %d')} - {trip['end_date'].strftime('%b %d, %Y')}</p>
                    <p><strong>Photos:</strong> {trip['photos']}</p>
                    <a href="{rel_html}" target="_blank">View Map</a>
                    <a href="{rel_gpx}" download>Download GPX</a>
                </div>
""")
            
            f.write("""
            </div>
        </div>
""")
        
        f.write("""
    </div>
</body>
</html>
""")

def find_all_gpx_files(search_dirs):
    """Find all GPX files in the provided directories"""
    gpx_files = []
    for directory in search_dirs:
        if os.path.isdir(directory):
            for root, _, files in os.walk(directory):
                for file in files:
                    if file.lower().endswith('.gpx'):
                        gpx_files.append(os.path.join(root, file))
    return gpx_files

def parse_date_range(date_str):
    """Parse date range string in format YYYY-MM-DD:YYYY-MM-DD"""
    try:
        if ':' in date_str:
            start_str, end_str = date_str.split(':')
            start_date = datetime.strptime(start_str.strip(), '%Y-%m-%d').date()
            end_date = datetime.strptime(end_str.strip(), '%Y-%m-%d').date()
        else:
            # Assume single date means that day only
            start_date = datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
            end_date = start_date
        
        return start_date, end_date
    except ValueError:
        print(f"Invalid date range format: {date_str}. Use YYYY-MM-DD:YYYY-MM-DD")
        return None

def create_custom_route_from_cities(cities, start_date_str=None, dates_list=None, output_gpx="custom_route.gpx", output_html="custom_route.html", custom_locations=None):
    """Create a custom route from a list of city names with optional specific dates
    
    Parameters:
    - cities: List of location names to geocode
    - start_date_str: Starting date in YYYY-MM-DD format
    - dates_list: List of datetime objects for each location
    - output_gpx: Filename for GPX output
    - output_html: Filename for HTML map output
    - custom_locations: Dictionary mapping location names to (lat, lon) coordinates for hard-to-find places
    """
    print(f"Creating custom route with {len(cities)} locations:")
    for i, city in enumerate(cities):
        print(f"{i+1}. {city}")
    
    # Set default start date to today if not provided
    start_date = datetime.now()
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        except ValueError:
            print(f"Invalid date format: {start_date_str}. Using current date instead.")
    
    # Initialize geocoder
    geolocator = Nominatim(user_agent="photo-trip-scheduler")
    
    # Create a GPX file
    gpx = gpxpy.gpx.GPX()
    track = gpxpy.gpx.GPXTrack(name="Custom Route")
    gpx.tracks.append(track)
    segment = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(segment)
    
    # For map visualization
    points = []
    
    # Use empty dictionary if no custom locations provided
    if custom_locations is None:
        custom_locations = {}
    
    # Process each city
    for i, city in enumerate(cities):
        print(f"Geocoding {city}...")
        
        # Check if we have manual coordinates for this location
        manual_coords = custom_locations.get(city)
        
        if manual_coords:
            lat, lon = manual_coords
            print(f"  Using custom coordinates: {lat:.5f}, {lon:.5f}")
        else:
            # Try geocoding
            try:
                location = geolocator.geocode(city)
                if location:
                    lat, lon = location.latitude, location.longitude
                    print(f"  Successfully geocoded: {lat:.5f}, {lon:.5f}")
                else:
                    print(f"  Could not find coordinates for {city}")
                    continue
            except Exception as e:
                print(f"  Error geocoding {city}: {e}")
                continue
            
            # Be nice to the geocoding service
            time.sleep(1)
        
        # Determine point time: use provided date or increment from start date
        if dates_list and i < len(dates_list):
            point_time = dates_list[i]
        else:
            point_time = start_date + timedelta(days=i)  # Simple progression, one day per city
        
        # Add point to GPX
        point = gpxpy.gpx.GPXTrackPoint(
            latitude=lat,
            longitude=lon,
            time=point_time,
            name=city
        )
        segment.points.append(point)
        
        # Add to visualization data
        points.append((point_time, lat, lon, None, city))
        print(f"  Added {city}: {lat:.5f}, {lon:.5f} on {point_time.strftime('%Y-%m-%d')}")
    
    if not points:
        print("Could not geocode any locations. Route creation failed.")
        return
    
    # Save GPX file
    route_folder = ensure_route_folder(os.getcwd())
    gpx_path = os.path.join(route_folder, output_gpx)
    with open(gpx_path, 'w') as f:
        f.write(gpx.to_xml())
    print(f"GPX file saved to {gpx_path}")
    
    # Create visualization
    html_path = os.path.join(route_folder, output_html)
    
    # Export map
    export_advanced_map([points], html_path)
    print(f"Interactive map saved to {html_path}")
    
    return points

def main():
    parser = argparse.ArgumentParser(description="PhotoTripMaker V6 - Find and reconstruct old holiday routes from photos")
    
    # Input sources
    parser.add_argument("folder", help="Folder with photos", nargs='?', default=None)
    parser.add_argument("--multi-folders", nargs='+', help="Process multiple photo folders and merge them")
    parser.add_argument("--gpx-import", help="Import GPX file to use as reference track")
    parser.add_argument("--gpx-search", nargs='+', help="Search directories for GPX files")
    
    # Output parameters
    parser.add_argument("output_gpx", help="Output GPX filename (will be saved in Route subfolder)", nargs='?', default="trip.gpx")
    parser.add_argument("output_md", help="Output Markdown summary filename (will be saved in Route subfolder)", nargs='?', default="trip.md")
    parser.add_argument("output_csv", help="Output CSV helper filename (will be saved in Route subfolder)", nargs='?', default="trip.csv")
    parser.add_argument("output_html", help="Output HTML map filename (will be saved in Route subfolder)", nargs='?', default="trip.html")
    
    # Processing options
    parser.add_argument("--geocode", action='store_true', help="Reverse geocode locations (slow)")
    parser.add_argument("--gap", type=int, default=4, help="Time gap (hours) for clustering")
    parser.add_argument("--distance", type=float, default=25.0, help="Distance gap (km) for clustering")
    parser.add_argument("--tz-shift", type=int, default=0, help="Timezone shift in hours")
    parser.add_argument("--date-range", help="Filter photos by date range (format: YYYY-MM-DD:YYYY-MM-DD)")
    parser.add_argument("--min-photos", type=int, default=3, help="Minimum number of photos needed to create a trip")
    
    # Feature flags
    parser.add_argument("--infer", action='store_true', help="Try to infer locations for photos without GPS data")
    parser.add_argument("--manual", action='store_true', help="Manually input locations for photos without GPS data")
    parser.add_argument("--filename-dates", action='store_true', help="Extract dates from filenames when EXIF is missing")
    parser.add_argument("--advanced-map", action='store_true', help="Create advanced HTML map with timeline and heatmap")
    parser.add_argument("--skip-preview", action='store_true', help="Skip interactive preview and proceed with file generation")
    parser.add_argument("--gpx-as-route", action='store_true', help="Treat imported GPX file as a single route (no clustering)")
    
    # Batch processing
    parser.add_argument("--batch", help="Batch process multiple folders under root directory")
    parser.add_argument("--batch-output", help="Output directory for batch processing", default="TripArchive")
    
    # Custom route options
    parser.add_argument("--route-cities", nargs='+', help="Define a custom route with a list of cities")
    parser.add_argument("--route-dates", nargs='+', help="Specific dates for the route points (format: YYYY-MM-DD for each point)")
    parser.add_argument("--route-start-date", help="Optional start date for the custom route (format: YYYY-MM-DD)")
    parser.add_argument("--route-gpx-output", help="Output GPX filename for custom route", default="custom_route.gpx")
    parser.add_argument("--route-html-output", help="Output HTML filename for custom route", default="custom_route.html")
    parser.add_argument("--custom-locations-file", help="JSON file containing custom location coordinates")
    
    args = parser.parse_args()
    
    # Handle custom route creation if cities are provided
    if args.route_cities and len(args.route_cities) > 0:
        # Convert route dates if provided
        route_dates = None
        if args.route_dates and len(args.route_dates) > 0:
            route_dates = []
            for date_str in args.route_dates:
                try:
                    date = datetime.strptime(date_str, '%Y-%m-%d')
                    route_dates.append(date)
                except ValueError:
                    print(f"Warning: Invalid date format '{date_str}', expected YYYY-MM-DD. Ignoring this date.")
        
        # Use specific output filenames for routes
        output_gpx = args.route_gpx_output
        output_html = args.route_html_output
        
        # Load custom locations if provided
        custom_locations = {}
        if args.custom_locations_file and os.path.exists(args.custom_locations_file):
            try:
                with open(args.custom_locations_file, 'r') as f:
                    custom_locations = json.load(f)
                print(f"Loaded {len(custom_locations)} custom locations from {args.custom_locations_file}")
            except Exception as e:
                print(f"Error loading custom locations file: {e}")
        
        create_custom_route_from_cities(
            args.route_cities, 
            args.route_start_date, 
            route_dates, 
            output_gpx, 
            output_html,
            custom_locations
        )
        print(f"Custom route created. You can now process your photos using:")
        print(f"python main.py YOUR_PHOTO_FOLDER --gpx-import Route/{output_gpx} --infer --filename-dates --gpx-as-route")
        return
    
    # Set up date range filter if provided
    date_range = None
    if args.date_range:
        date_range = parse_date_range(args.date_range)
        if not date_range:
            return
    
    # Batch processing mode
    if args.batch:
        print(f"Starting batch processing from {args.batch}")
        trip_count = batch_process_folders(
            args.batch, args.batch_output, 
            tz_shift=args.tz_shift,
            time_gap_hours=args.gap, 
            distance_km=args.distance,
            infer_locations=args.infer,
            use_filename_dates=args.filename_dates,
            geocode=args.geocode
        )
        print(f"\nBatch processing complete. Created {trip_count} trips in {args.batch_output}")
        print(f"Open {os.path.join(args.batch_output, 'index.html')} to browse all trips")
        return

    # Check if we have a source of photos
    if not args.folder and not args.multi_folders and not args.gpx_import and not args.gpx_search:
        parser.print_help()
        print("\nERROR: You must specify at least one source of data (folder, multi-folders, gpx-import, or gpx-search)")
        return
    
    # Load data from different sources
    all_photos = []
    gpx_points = []
    
    # 1. Process regular photos folder
    if args.folder:
        print(f"Processing photos from {args.folder}")
        gps_photos, non_gps_photos, location_cache = scan_photos(
            args.folder, args.tz_shift, args.infer, args.filename_dates, date_range)
        
        # Handle photos without GPS data
        if non_gps_photos:
            if args.infer:
                enriched = infer_coordinates(non_gps_photos, gps_photos, location_cache, args.folder)
                all_photos.extend(enriched)
            elif args.manual:
                enriched = interactive_location_input(non_gps_photos, args.folder)
                all_photos.extend(enriched)
            else:
                print(f"Warning: {len(non_gps_photos)} photos don't have GPS data and won't be included.")
                print("Use --infer or --manual to include these photos.")
        
        # Add photos with GPS data
        all_photos.extend(gps_photos)
    
    # 2. Process multiple photo folders
    if args.multi_folders:
        print(f"Processing {len(args.multi_folders)} folders")
        merged_gps, merged_non_gps = scan_multiple_folders(
            args.multi_folders, args.tz_shift, args.infer, args.filename_dates, date_range)
        
        # Add GPS photos from all folders
        all_photos.extend(merged_gps)
        
        # Handle non-GPS photos from all folders
        if merged_non_gps:
            if args.infer:
                for folder in args.multi_folders:
                    folder_photos = [p for p in merged_non_gps if p[4].startswith(folder)]
                    if folder_photos:
                        location_cache = load_location_cache(folder)
                        folder_gps = [p for p in merged_gps if p[4].startswith(folder)]
                        enriched = infer_coordinates(folder_photos, folder_gps, location_cache, folder)
                        all_photos.extend(enriched)
            elif args.manual:
                for folder in args.multi_folders:
                    folder_photos = [p for p in merged_non_gps if p[4].startswith(folder)]
                    if folder_photos:
                        enriched = interactive_location_input(folder_photos, folder)
                        all_photos.extend(enriched)
            else:
                print(f"Warning: {len(merged_non_gps)} photos don't have GPS data and won't be included.")
    
    # 3. Import GPX file
    if args.gpx_import:
        print(f"Importing GPX file: {args.gpx_import}")
        gpx_points = load_gpx_tracks(args.gpx_import)
        if args.gpx_as_route:
            print("Treating GPX file as a single route")
        else:
            all_photos.extend(gpx_points)
    
    # 4. Search for GPX files
    if args.gpx_search:
        gpx_files = find_all_gpx_files(args.gpx_search)
        print(f"Found {len(gpx_files)} GPX files")
        for gpx_file in gpx_files:
            print(f"Loading GPX file: {gpx_file}")
            file_gpx_points = load_gpx_tracks(gpx_file)
            all_photos.extend(file_gpx_points)
    
    # Special case for imported GPX as a route
    if args.gpx_import and args.gpx_as_route:
        # When specifically importing a GPS route, treat it as a single segment
        clusters = [gpx_points]
        print(f"Using imported GPX route with {len(gpx_points)} points as a single segment")
    else:
        # Normal processing with clustering
        # Sort all data points by time
        all_photos = sorted(all_photos, key=lambda x: x[0])
        
        if not all_photos:
            print("No usable photos or GPX data found. Cannot generate trip.")
            return
        
        print(f"\nFound {len(all_photos)} total photos/points with location data")
        
        # Cluster data points into trip segments
        clusters = cluster_photos(all_photos, args.gap, args.distance)
        print(f"Identified {len(clusters)} trip segments")
        
        # Filter out small clusters
        if args.min_photos > 0:
            original_count = len(clusters)
            clusters = [c for c in clusters if len(c) >= args.min_photos]
            if len(clusters) < original_count:
                print(f"Filtered out {original_count - len(clusters)} segments with fewer than {args.min_photos} photos")
    
    if not clusters:
        print("No valid trip segments found after filtering.")
        return
    
    # Show preview and confirm
    if not args.skip_preview and not interactive_preview(clusters):
        print("Operation cancelled by user.")
        return
    
    # Determine output location
    output_folder = args.folder if args.folder else os.getcwd()
    route_folder = ensure_route_folder(output_folder)
    
    # Generate output files
    gpx_path = os.path.join(route_folder, args.output_gpx)
    md_path = os.path.join(route_folder, args.output_md)
    csv_path = os.path.join(route_folder, args.output_csv)
    html_path = os.path.join(route_folder, args.output_html)
    
    create_gpx(clusters, gpx_path)
    write_summary(clusters, md_path, args.geocode)
    export_csv(clusters, csv_path, args.geocode)
    
    if args.advanced_map:
        export_advanced_map(clusters, html_path)
    else:
        export_map(clusters, html_path)
    
    print("\nFinished! Output files:")
    print(f"GPX track: {gpx_path}")
    print(f"Markdown summary: {md_path}")
    print(f"CSV for Polarsteps: {csv_path}")
    print(f"HTML map: {html_path}")

if __name__ == "__main__":
    main()