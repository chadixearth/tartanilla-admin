document.addEventListener('DOMContentLoaded', () => {
    const currentUserId = window.adminUserId;
    let activeConversationId = null;
    
    // Listen for loaded conversations
    document.addEventListener('conversationsLoaded', (event) => {
        renderConversations(event.detail.conversations);
    });
    
    // Listen for filtered conversations
    document.addEventListener('conversationsFiltered', (event) => {
        renderConversations(event.detail.conversations);
        
        // Show empty state if no results
        if (event.detail.conversations.length === 0) {
            const conversationsList = document.getElementById('conversationsList');
            if (conversationsList) {
                let message = '';
                
                if (event.detail.filterType === 'search') {
                    message = `No conversations found matching "${event.detail.query}"`;
                } else if (event.detail.filterType === 'tab') {
                    message = `No ${event.detail.filter} conversations found`;
                }
                
                conversationsList.innerHTML = `
                    <div class="text-center py-12 px-4">
                        <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" 
                                d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        <h3 class="mt-2 text-sm font-medium text-gray-900">No Results</h3>
                        <p class="mt-1 text-sm text-gray-500">${message}</p>
                    </div>`;
            }
        }
    });
    
    // Function to render the conversation list
    function renderConversations(conversations) {
        const conversationsList = document.getElementById('conversationsList');
        if (!conversationsList) return;
        
        // If no conversations, handle empty state
        if (!conversations || conversations.length === 0) {
            return;
        }
        
        conversationsList.innerHTML = '';
        
        conversations.forEach(conversation => {
            // Determine who the other user is (since current user could be user1 or user2)
            const otherUser = conversation.user1_id === currentUserId ? 
                conversation.user2 : conversation.user1;
            
            const lastMessage = conversation.last_message || 'No messages yet';
            const lastMessageTime = conversation.last_message_time ? 
                formatMessageTime(new Date(conversation.last_message_time)) : '';
            
            // Create conversation list item
            const conversationItem = document.createElement('div');
            
            // Set class based on whether this is the active conversation
            conversationItem.className = `p-4 border-b border-gray-100 cursor-pointer transition-colors
                ${conversation.id === activeConversationId ? 'bg-[#accent-lightest]' : 'hover:bg-gray-50'}`;
            conversationItem.dataset.conversationId = conversation.id;
            
            // Set conversation item content
            conversationItem.innerHTML = `
                <div class="flex items-start space-x-3">
                    <div class="relative">
                        <img src="${otherUser.profile_photo_url || '/static/img/TarTrack Logo_sakto.png'}" 
                             alt="${otherUser.name}" 
                             class="w-12 h-12 rounded-full object-cover"
                             onerror="this.src='/static/img/TarTrack Logo_sakto.png'">
                    </div>
                    <div class="flex-1 min-w-0">
                        <div class="flex justify-between items-center">
                            <h3 class="text-sm font-semibold text-[#561c24] truncate">${otherUser.name}</h3>
                            <span class="text-xs text-gray-500">${lastMessageTime}</span>
                        </div>
                        <p class="text-xs text-gray-600 mb-1">${otherUser.role}</p>
                        <p class="text-sm text-gray-700 truncate">${lastMessage}</p>
                        <div class="flex justify-between items-center mt-1">
                            ${conversation.unread_count > 0 ? 
                                `<span class="bg-[#561c24] text-white text-xs px-2 py-1 rounded-full">${conversation.unread_count}</span>` 
                                : ''}
                        </div>
                    </div>
                </div>
            `;
            
            // Add click handler for conversation selection
            conversationItem.addEventListener('click', () => {
                setActiveConversation(conversation.id);
                
                // Dispatch event for message loading
                document.dispatchEvent(new CustomEvent('conversationSelected', {
                    detail: { 
                        conversationId: conversation.id,
                        otherUser: otherUser 
                    }
                }));
            });
            
            conversationsList.appendChild(conversationItem);
        });
    }
    
    // Helper function to format message time
    function formatMessageTime(date) {
        const now = new Date();
        const yesterday = new Date(now);
        yesterday.setDate(now.getDate() - 1);
        
        // Same day formatting
        if (date.toDateString() === now.toDateString()) {
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } 
        // Yesterday formatting
        else if (date.toDateString() === yesterday.toDateString()) {
            return 'Yesterday';
        } 
        // This week formatting
        else if (now - date < 7 * 24 * 60 * 60 * 1000) {
            return date.toLocaleDateString([], { weekday: 'long' });
        } 
        // Other dates
        else {
            return date.toLocaleDateString();
        }
    }
    
    // Set active conversation and update UI
    function setActiveConversation(conversationId) {
        activeConversationId = conversationId;
        
        // Update UI to show active conversation
        const allConversationItems = document.querySelectorAll('#conversationsList > div');
        allConversationItems.forEach(item => {
            if (item.dataset.conversationId === conversationId.toString()) {
                item.classList.add('bg-[#accent-lightest]');
                item.classList.remove('hover:bg-gray-50');
            } else {
                item.classList.remove('bg-[#accent-lightest]');
                item.classList.add('hover:bg-gray-50');
            }
        });
    }
});