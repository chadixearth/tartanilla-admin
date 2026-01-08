async function fetchExistingItems() {
    try {
        console.log('Fetching map data...');
        const response = await fetch('/routemanagement/raw_json/');
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const text = await response.text();
        console.log('Raw response:', text);
        
        if (!text || text.trim() === '') {
            throw new Error('Empty response from server');
        }
        
        const data = JSON.parse(text);
        console.log('Parsed data:', data);
        
        if (data.success) {
            clearMapItems();
            
            let itemCount = 0;
            
            if (data.points && data.points.length > 0) {
                console.log('Displaying', data.points.length, 'points');
                displayExistingPoints(data.points);
                itemCount += data.points.length;
            }
            
            if (data.roads && data.roads.length > 0) {
                console.log('Roads data received:', data.roads);
                displayExistingRoads(data.roads);
                itemCount += data.roads.length;
            } else {
                console.log('No roads found in data');
            }
            
            if (itemCount > 0) {
                showSuccessMessage(`Loaded ${data.points?.length || 0} points and ${data.roads?.length || 0} roads`);
            } else {
                console.log('No map data found');
            }
        } else {
            throw new Error(data.error || 'Server returned error');
        }
        
    } catch (err) {
        console.error('Load error:', err);
        console.log('Map loaded but data fetch failed:', err.message);
    }
}