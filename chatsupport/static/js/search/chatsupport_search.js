document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.querySelector('input[placeholder="Search conversations..."]');
    
    if (!searchInput) return;
    
    let allSupportConversations = [];
    let debounceTimer;
    
    // Listen for loaded conversations to store them
    document.addEventListener('supportConversationsLoaded', (event) => {
        // Store conversations only if it's an initial load, not a filtered result
        if (!event.detail.filterType) {
            allSupportConversations = event.detail.conversations || [];
        }
    });
    
    // Add input event listener with debounce
    searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            performSearch(searchInput.value.trim().toLowerCase());
        }, 300); // 300ms debounce
    });
    
    function performSearch(query) {
        // If search is empty, show all conversations but respect current filters
        if (!query) {
            // Reload using current filters
            document.dispatchEvent(new Event('reloadSupportConversations'));
            return;
        }
        
        // Get current status filter
        const statusFilter = window.currentStatusFilter || 'open';
        
        // Filter conversations based on search query AND current status filter
        const filteredConversations = allSupportConversations.filter(conversation => {
            // Skip if no user data
            if (!conversation.user) return false;
            
            // First apply status filter
            if (statusFilter.includes(',')) {
                // Multiple statuses (e.g., "resolved,closed")
                const statuses = statusFilter.split(',').map(s => s.trim());
                if (!statuses.includes(conversation.status)) return false;
            } else {
                // Single status
                if (conversation.status !== statusFilter) return false;
            }
            
            // Then apply search query
            // Search in user name and role
            if (conversation.user.name && 
                conversation.user.name.toLowerCase().includes(query)) return true;
                
            if (conversation.user.role && 
                conversation.user.role.toLowerCase().includes(query)) return true;
            
            // Search in subject
            if (conversation.subject && 
                conversation.subject.toLowerCase().includes(query)) return true;
            
            return false;
        });
        
        // Update the UI with filtered conversations
        document.dispatchEvent(new CustomEvent('supportConversationsLoaded', { 
            detail: { 
                conversations: filteredConversations, 
                filterType: 'search', 
                query: query 
            }
        }));
    }
});