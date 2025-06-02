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
let userDefinedDataPath = ''; // Will hold the path from Neutralino.os.getPath('data')

// Function to fetch song data from backend and update UI
async function fetchAndUpdateSongData() {
    if (statusMessageElement) statusMessageElement.textContent = 'Fetching song data...';

    if (!userDefinedDataPath) {
        console.warn("User data path not yet available. Backend will use default.");
        // Optionally, you could prevent the call or wait, but for now, let Python handle default.
    }

    try {
        const payload = {
            command: 'handle_get_current_song_data',
            dataPath: userDefinedDataPath
        };

        let response = await Neutralino.extensions.exec({
            id: 'org.songpi.pythonbackend',
            data: JSON.stringify(payload) // Send command and dataPath as a JSON string
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
            } else if (err.code === 'NE_OS_INVPATHP') {
                 statusMessageElement.textContent = `Error obtaining path: ${err.message}. Backend will use default.`;
                 console.error("NE_OS_INVPATHP error, likely from getPath('data') if it was called incorrectly or failed.");
            }
            else {
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
        if (coverArtElement) coverArtElement.src = data.cover_art_base64;
    } else {
        if (coverArtElement) coverArtElement.src = 'icons/appIcon.png'; // Default image
    }

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

    songHistoryContainer.innerHTML = '<h2>History</h2>';

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
async function onWindowLoaded() { // Made async to use await for getPath
    if(Neutralino.settings.isDev) {
        console.log("Development mode detected by Neutralino.");
    }

    try {
        userDefinedDataPath = await Neutralino.os.getPath('data');
        console.log(`User data path: ${userDefinedDataPath}`);
        // Store globally for easier access if needed, or pass to functions
        window.NL_USER_DATA_PATH = userDefinedDataPath;
    } catch (err) {
        console.error("Error getting user data path:", err);
        if (statusMessageElement) statusMessageElement.textContent = "Could not get user data directory. Using default.";
        // Backend will use its default path if userDefinedDataPath is empty or not provided.
    }

    // Fetch initial song data
    await fetchAndUpdateSongData(); // Make sure this call also awaits if it becomes async at top level

    // Start periodic updates
    if (songUpdateIntervalId) clearInterval(songUpdateIntervalId);
    songUpdateIntervalId = setInterval(fetchAndUpdateSongData, UPDATE_INTERVAL_MS);
    console.log(`Started periodic song data fetching every ${UPDATE_INTERVAL_MS}ms.`);
}

// Set the onWindowLoaded event
Neutralino.events.on("windowReady", onWindowLoaded);

// Fallback if event isn't triggered
// Added a flag to prevent double execution with the event listener.
if (typeof window.NL_WINDOWREADYEVENTTRIGGERED === 'undefined') {
    window.NL_WINDOWREADYEVENTTRIGGERED = false;
}
Neutralino.events.on("windowReady", () => { window.NL_WINDOWREADYEVENTTRIGGERED = true; });

if (window.NL_LOADED && !window.NL_WINDOWREADYEVENTTRIGGERED) {
    console.warn("windowReady event not triggered, using NL_LOADED fallback for onWindowLoaded.");
    onWindowLoaded();
}


// Clear interval on window close
Neutralino.events.on('windowClose', () => {
    if (songUpdateIntervalId) {
        clearInterval(songUpdateIntervalId);
        console.log('Cleared song update interval due to windowClose event.');
    }
});
