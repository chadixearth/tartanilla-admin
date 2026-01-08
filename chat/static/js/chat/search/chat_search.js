document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.querySelector('input[placeholder="Search conversations..."]');
    
    if (!searchInput) return;
    
    let allConversations = [];
    let debounceTimer;
    
    // Listen for loaded conversations to store them
    document.addEventListener('conversationsLoaded', (event) => {
        allConversations = event.detail.conversations;
    });
    
    // Add input event listener with debounce
    searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            performSearch(searchInput.value.trim().toLowerCase());
        }, 300); // 300ms debounce
    });
    
    function performSearch(query) {
        // If search is empty, show all conversations
        if (!query) {
            document.dispatchEvent(new CustomEvent('conversationsLoaded', { 
                detail: { conversations: allConversations }
            }));
            return;
        }
        
        // Filter conversations based on search query
        const filteredConversations = allConversations.filter(conversation => {
            // Determine which user is the "other" user
            const currentUserId = window.adminUserId;
            const otherUser = conversation.user1_id === currentUserId ? 
                conversation.user2 : conversation.user1;
            
            // Search in user name and role
            if (otherUser.name && otherUser.name.toLowerCase().includes(query)) return true;
            if (otherUser.role && otherUser.role.toLowerCase().includes(query)) return true;
            
            // Search in last message
            if (conversation.last_message && conversation.last_message.toLowerCase().includes(query)) return true;
            
            return false;
        });
        
        // Update the UI with filtered conversations
        document.dispatchEvent(new CustomEvent('conversationsFiltered', { 
            detail: { conversations: filteredConversations, filterType: 'search', query: query }
        }));
    }
});