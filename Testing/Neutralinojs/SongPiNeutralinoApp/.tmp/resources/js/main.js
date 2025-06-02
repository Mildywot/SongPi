// Initialize Neutralino
Neutralino.init();

// DOM Element References
const coverArtElement = document.getElementById('coverArt');
const songTitleElement = document.getElementById('songTitle');
const songArtistElement = document.getElementById('songArtist');
const statusMessageElement = document.getElementById('statusMessage');
const songHistoryContainer = document.getElementById('songHistory');
const testBackendButton = document.getElementById('testBackendButton');

let songUpdateIntervalId = null;
const UPDATE_INTERVAL_MS = 5000; // 5 seconds, make configurable later if needed

// Function to fetch song data from backend and update UI
async function fetchAndUpdateSongData() {
    if (statusMessageElement) statusMessageElement.textContent = 'Fetching song data...';
    try {
        let response = await Neutralino.extensions.exec({
            id: 'org.songpi.pythonbackend',
            data: 'handle_get_current_song_data'
        });

        console.log('Backend Response (raw):', response.stdout);

        if (response.stdout) {
            try {
                const songData = JSON.parse(response.stdout);
                console.log('Parsed songData:', songData);
                updateSongDisplay(songData);
            } catch (e) {
                console.error("Error parsing backend JSON:", e, "\nRaw stdout:", response.stdout);
                if (statusMessageElement) statusMessageElement.textContent = `Error parsing response: ${e.message}`;
            }
        } else if (response.stderr) {
            console.error('Backend error:', response.stderr);
            if (statusMessageElement) statusMessageElement.textContent = `Backend error: ${response.stderr}`;
        } else {
             console.warn('Backend response received, but not in expected format (no stdout/stderr).', response);
             if (statusMessageElement) statusMessageElement.textContent = 'Empty or unexpected response from backend.';
        }
    } catch (err) {
        console.error('Error calling backend extension:', err);
        if (statusMessageElement) {
            if (err.code === 'NE_EX_EXTNOTSUPPORTED') {
                 statusMessageElement.textContent = 'Extension not supported or ID mismatch. Check neutralino.config.json.';
            } else {
                 statusMessageElement.textContent = `Error calling backend: ${err.message}`;
            }
        }
    }
}

// Function to update song display
function updateSongDisplay(data) {
    if (!data) {
        console.warn("updateSongDisplay called with no data.");
        if (songTitleElement) songTitleElement.textContent = '---';
        if (songArtistElement) songArtistElement.textContent = '---';
        if (coverArtElement) coverArtElement.src = 'icons/appIcon.png'; // Default image
        if (statusMessageElement) statusMessageElement.textContent = 'No data received.';
        return;
    }

    if (songTitleElement) songTitleElement.textContent = data.title || '---';
    if (songArtistElement) songArtistElement.textContent = data.artist || '---';

    if (data.cover_art_base64) {
        // The backend now sends data:image/jpeg;base64,
        if (coverArtElement) coverArtElement.src = data.cover_art_base64;
    } else {
        if (coverArtElement) coverArtElement.src = 'icons/appIcon.png'; // Default image
    }

    // Use status_message from backend if available, otherwise a generic "Ready"
    if (statusMessageElement) {
        statusMessageElement.textContent = data.status_message || 'Ready';
    }
}


// Event Listener for the Test Backend Button (Manual Trigger)
if (testBackendButton) {
    testBackendButton.addEventListener('click', fetchAndUpdateSongData);
} else {
    console.error("Test Backend Button not found!");
}

// Placeholder function to update history display
function updateHistoryDisplay(historyArray) {
    if (!songHistoryContainer) return;

    songHistoryContainer.innerHTML = '<h2>History</h2>'; // Clear previous history

    if (Array.isArray(historyArray) && historyArray.length > 0) {
        const list = document.createElement('ul');
        historyArray.forEach(item => {
            const listItem = document.createElement('li');
            listItem.className = 'historyItem';

            const titleEl = document.createElement('p');
            titleEl.textContent = `Title: ${item.title || 'Unknown'}`;
            const artistEl = document.createElement('p');
            artistEl.textContent = `Artist: ${item.artist || 'Unknown'}`;

            listItem.appendChild(titleEl);
            listItem.appendChild(artistEl);
            list.appendChild(listItem);
        });
        songHistoryContainer.appendChild(list);
    } else {
        const noHistoryMessage = document.createElement('p');
        noHistoryMessage.textContent = 'No song history available yet.';
        songHistoryContainer.appendChild(noHistoryMessage);
    }
}

// Function to be called when Neutralino is ready / window is loaded
function onWindowLoaded() {
    if(Neutralino.settings.isDev) {
        console.log("Development mode detected by Neutralino.");
    }

    // Fetch initial song data
    fetchAndUpdateSongData();

    // Start periodic updates
    if (songUpdateIntervalId) clearInterval(songUpdateIntervalId); // Clear existing interval if any
    songUpdateIntervalId = setInterval(fetchAndUpdateSongData, UPDATE_INTERVAL_MS);
    console.log(`Started periodic song data fetching every ${UPDATE_INTERVAL_MS}ms.`);
}

// Set the onWindowLoaded event
Neutralino.events.on("windowReady", onWindowLoaded);

// Fallback if event isn't triggered
if (window.NL_LOADED && !window.NL_WINDOWREADYEVENTTRIGGERED) {
    console.warn("windowReady event not triggered, using NL_LOADED fallback for onWindowLoaded.");
    onWindowLoaded();
}
// To prevent double execution if both NL_LOADED and windowReady trigger.
Neutralino.events.on("windowReady", () => { window.NL_WINDOWREADYEVENTTRIGGERED = true; });


// Clear interval on window close
Neutralino.events.on('windowClose', () => {
    if (songUpdateIntervalId) {
        clearInterval(songUpdateIntervalId);
        console.log('Cleared song update interval due to windowClose event.');
    }
    // Neutralino.app.exit(); // Not strictly needed here as window is closing
});
