document.addEventListener('DOMContentLoaded', function() {
    // User dropdown toggle
    const userMenuButton = document.getElementById('userMenuButton');
    const userDropdown = document.getElementById('userDropdown');
    const notificationButton = document.getElementById('notificationButton');
    const notificationDropdown = document.getElementById('notificationDropdown');

    // Toggle user dropdown
    if (userMenuButton && userDropdown) {
        userMenuButton.addEventListener('click', function(e) {
            e.stopPropagation();
            userDropdown.classList.toggle('hidden');
            userDropdown.classList.toggle('user-dropdown-enter-active');
            
            // Close notification dropdown if open
            if (notificationDropdown) {
                notificationDropdown.classList.add('hidden');
                notificationDropdown.classList.remove('user-dropdown-enter-active');
            }
        });
    }

    // Toggle notification dropdown
    if (notificationButton && notificationDropdown) {
        notificationButton.addEventListener('click', function(e) {
            e.stopPropagation();
            notificationDropdown.classList.toggle('hidden');
            notificationDropdown.classList.toggle('user-dropdown-enter-active');
            
            // Close user dropdown if open
            if (userDropdown) {
                userDropdown.classList.add('hidden');
                userDropdown.classList.remove('user-dropdown-enter-active');
            }
        });
    }

    // Close dropdowns when clicking outside
    document.addEventListener('click', function(e) {
        if (userDropdown && !userMenuButton.contains(e.target) && !userDropdown.contains(e.target)) {
            userDropdown.classList.add('hidden');
            userDropdown.classList.remove('user-dropdown-enter-active');
        }
        
        if (notificationDropdown && !notificationButton.contains(e.target) && !notificationDropdown.contains(e.target)) {
            notificationDropdown.classList.add('hidden');
            notificationDropdown.classList.remove('user-dropdown-enter-active');
        }
    });

    // Search functionality
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                const searchTerm = this.value.trim();
                if (searchTerm) {
                    // Implement search functionality here
                    console.log('Searching for:', searchTerm);
                }
            }
        });
    }

    // Real-time clock
    function updateClock() {
        const now = new Date();
        const timeString = now.toLocaleTimeString('en-US', {
            hour12: true,
            hour: '2-digit',
            minute: '2-digit'
        });
        const clockElement = document.getElementById('currentTime');
        if (clockElement) {
            clockElement.textContent = timeString;
        }
    }

    // Update clock every second
    updateClock();
    setInterval(updateClock, 1000);
});