document.addEventListener('DOMContentLoaded', () => {
    // Get all filter tabs
    const allTab = document.querySelector('button.text-sm:nth-child(1)');
    const driversTab = document.querySelector('button.text-sm:nth-child(2)');
    const ownersTab = document.querySelector('button.text-sm:nth-child(3)');
    const touristsTab = document.querySelector('button.text-sm:nth-child(4)');
    
    let allConversations = [];
    let currentFilter = 'all';
    
    // Listen for loaded conversations to store them
    document.addEventListener('conversationsLoaded', (event) => {
        allConversations = event.detail.conversations;
        
        // Re-apply current filter when conversations are loaded/reloaded
        if (currentFilter !== 'all') {
            applyFilter(currentFilter);
        }
    });
    
    // Set up click handlers for each tab
    if (allTab) {
        allTab.addEventListener('click', () => {
            setActiveTab(allTab);
            currentFilter = 'all';
            document.dispatchEvent(new CustomEvent('conversationsFiltered', { 
                detail: { conversations: allConversations, filterType: 'tab', filter: 'all' }
            }));
        });
    }
    
    if (driversTab) {
        driversTab.addEventListener('click', () => {
            setActiveTab(driversTab);
            currentFilter = 'driver';
            applyFilter('driver');
        });
    }
    
    if (ownersTab) {
        ownersTab.addEventListener('click', () => {
            setActiveTab(ownersTab);
            currentFilter = 'owner';
            applyFilter('owner');
        });
    }
    
    if (touristsTab) {
        touristsTab.addEventListener('click', () => {
            setActiveTab(touristsTab);
            currentFilter = 'tourist';
            applyFilter('tourist');
        });
    }
    
    // Helper function to apply filter
    function applyFilter(roleFilter) {
        const currentUserId = window.adminUserId;
        
        const filteredConversations = allConversations.filter(conversation => {
            // Get the other user
            const otherUser = conversation.user1_id === currentUserId ? 
                conversation.user2 : conversation.user1;
                
            // Check if user role matches filter (case insensitive)
            return otherUser.role && otherUser.role.toLowerCase() === roleFilter.toLowerCase();
        });
        
        // Update the UI with filtered conversations
        document.dispatchEvent(new CustomEvent('conversationsFiltered', { 
            detail: { conversations: filteredConversations, filterType: 'tab', filter: roleFilter }
        }));
    }
    
    // Helper to set active tab styling
    function setActiveTab(activeTab) {
        // Remove active state from all tabs
        [allTab, driversTab, ownersTab, touristsTab].forEach(tab => {
            if (tab) {
                tab.classList.remove('text-[#561c24]', 'border-b-2', 'border-[#561c24]', 'bg-[#accent-lightest]');
                tab.classList.add('text-gray-500');
            }
        });
        
        // Add active state to selected tab
        activeTab.classList.remove('text-gray-500');
        activeTab.classList.add('text-[#561c24]', 'border-b-2', 'border-[#561c24]', 'bg-[#accent-lightest]');
    }
});