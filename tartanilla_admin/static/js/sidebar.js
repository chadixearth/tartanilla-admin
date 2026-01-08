document.addEventListener('DOMContentLoaded', function() {
    const dropdownContainer = document.querySelector('.dropdown-container');
    const dropdownButton = dropdownContainer?.querySelector('.dropdown-button');
    const dropdownItems = dropdownContainer?.querySelector('.dropdown-items');
    const navItems = document.querySelectorAll('.nav-item:not(.dropdown-container)');
    
    // Handle dropdown functionality
    if (dropdownButton && dropdownItems) {
        // Close dropdown when clicking outside
        document.addEventListener('click', function(event) {
            if (!dropdownContainer.contains(event.target)) {
                dropdownContainer.classList.remove('open');
                dropdownItems.classList.add('hidden');
            }
        });

        // Toggle dropdown on button click
        dropdownButton.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            dropdownContainer.classList.toggle('open');
            dropdownItems.classList.toggle('hidden');
        });

        // Handle dropdown item clicks
        const dropdownLinks = dropdownItems.querySelectorAll('.dropdown-link');
        dropdownLinks.forEach(link => {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();

                // Remove active class from all nav items
                document.querySelectorAll('.nav-item').forEach(item => {
                    item.classList.remove('active');
                });

                // Add active class to parent dropdown
                dropdownContainer.classList.add('active');

                // Log the selected option (for now)
                console.log('Selected:', this.textContent.trim());

                // Navigate after a small delay to show the UI update
                const href = this.getAttribute('href');
                if (href && href !== '#') {
                    setTimeout(() => {
                        window.location.href = href;
                    }, 100);
                }
            });
        });
    }

    // Handle regular nav item clicks
    navItems.forEach(item => {
        item.addEventListener('click', function(e) {
            // Remove active class from all nav items
            document.querySelectorAll('.nav-item').forEach(navItem => {
                navItem.classList.remove('active');
            });
            
            // Add active class to clicked item
            this.classList.add('active');
            
            // Close dropdown if open
            if (dropdownContainer) {
                dropdownContainer.classList.remove('open');
                dropdownItems?.classList.add('hidden');
            }
        });
    });

    // Set active nav item based on current URL
    function setActiveNavItem() {
        const currentPath = window.location.pathname;
        const navLinks = document.querySelectorAll('.nav-link[href]');
        
        navLinks.forEach(link => {
            const linkPath = link.getAttribute('href');
            if (linkPath === currentPath) {
                const navItem = link.closest('.nav-item');
                navItem?.classList.add('active');
            }
        });
    }

    // Initialize active state
    setActiveNavItem();

    // Mobile menu toggle (if needed)
    const mobileMenuToggle = document.getElementById('mobileMenuToggle');
    const sidebar = document.querySelector('.sidebar');
    
    if (mobileMenuToggle && sidebar) {
        mobileMenuToggle.addEventListener('click', function() {
            sidebar.classList.toggle('open');
        });
    }
});