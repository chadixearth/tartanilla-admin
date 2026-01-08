document.addEventListener('DOMContentLoaded', () => {
    const currentUserId = window.adminUserId;
    
    if (!currentUserId || currentUserId === "") {
        return;
    }
    
    // Initialize Supabase subscriptions
    setupRealtimeSubscriptions();
    
    function setupRealtimeSubscriptions() {
        // Enable real-time capabilities for the client
        window.supabase.channel('public:conversations').subscribe();
        window.supabase.channel('public:messages').subscribe();
        
        // Listen for changes in conversations (new conversations, updates, deletes)
        const conversationChannel = window.supabase
            .channel('user-conversations')
            .on('postgres_changes', {
                event: '*',  // Listen for all events (INSERT, UPDATE, DELETE)
                schema: 'public',
                table: 'conversations',
                filter: `user1_id=eq.${currentUserId}`,
            }, handleConversationChange)
            .on('postgres_changes', {
                event: '*',
                schema: 'public',
                table: 'conversations',
                filter: `user2_id=eq.${currentUserId}`,
            }, handleConversationChange)
            .subscribe();
        
        // Listen for new messages that might affect conversation list
        const messageChannel = window.supabase
            .channel('user-messages')
            .on('postgres_changes', {
                event: 'INSERT',  // New messages
                schema: 'public',
                table: 'messages'
            }, handleNewMessage)
            .on('postgres_changes', {
                event: 'UPDATE',  // Message read status updates
                schema: 'public',
                table: 'messages',
                filter: `is_read=eq.true`
            }, handleMessageReadStatusChange)
            .subscribe();
            
        // Store channels for cleanup
        window.chatChannels = {
            conversationChannel,
            messageChannel
        };
        
        // Clean up subscriptions on page unload
        window.addEventListener('beforeunload', cleanupSubscriptions);
    }
    
    function handleConversationChange(payload) {
        // Get the current filter before reloading
        const currentFilterTab = document.querySelector('.border-b-2.border-\\[\\#561c24\\]');
        const currentFilter = currentFilterTab ? currentFilterTab.textContent.trim().toLowerCase() : 'all';
        
        // Handle conversation deletion specifically
        if (payload.eventType === 'DELETE') {
            // Check if this was the active conversation
            const activeConversationId = getActiveConversationId();
            if (activeConversationId && activeConversationId === payload.old.id) {
                // Reset active conversation view since it was deleted
                resetActiveConversationView();
            }
        }
        
        // Reload conversations for any conversation change
        document.dispatchEvent(new Event('reloadConversations'));
    }
    
    function handleNewMessage(payload) {
        // Extract the conversation ID and message details
        const message = payload.new;
        
        // Check if this message is relevant to the current user
        const isIncomingMessage = message.sender_id !== currentUserId;
        const isForCurrentUser = checkMessageForCurrentUser(message);
        
        if (isForCurrentUser) {
            // Update the conversation list to reflect new message
            document.dispatchEvent(new Event('reloadConversations'));
        }
    }
    
    function handleMessageReadStatusChange(payload) {
        // Reload conversations to update unread counts
        document.dispatchEvent(new Event('reloadConversations'));
    }
    
    // Helper function to check if a message belongs to a conversation of the current user
    async function checkMessageForCurrentUser(message) {
        try {
            const { data: conversation, error } = await window.supabase
                .from('conversations')
                .select('id')
                .eq('id', message.conversation_id)
                .or(`user1_id.eq.${currentUserId},user2_id.eq.${currentUserId}`)
                .single();
                
            return !error && conversation;
        } catch (err) {
            return false;
        }
    }
    
    // Helper function to get the active conversation ID
    function getActiveConversationId() {
        const activeConversation = document.querySelector('#conversationsList > div.bg-\\[\\#accent-lightest\\]');
        return activeConversation ? activeConversation.dataset.conversationId : null;
    }
    
    // Function to reset the active conversation view
    function resetActiveConversationView() {
        const messagesContainer = document.getElementById('messagesContainer');
        if (messagesContainer) {
            messagesContainer.innerHTML = `
                <div class="text-center py-12 px-4">
                    <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" 
                            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                    <h3 class="mt-2 text-sm font-medium text-gray-900">No active conversation</h3>
                    <p class="mt-1 text-sm text-gray-500">Select a conversation from the list or start a new one.</p>
                </div>`;
        }
        
        // Also reset the header
        const chatHeader = document.querySelector('.chat-header');
        if (chatHeader) {
            const nameElement = chatHeader.querySelector('h2');
            const roleElement = chatHeader.querySelector('.text-sm');
            
            if (nameElement) nameElement.textContent = 'No conversation selected';
            if (roleElement) roleElement.textContent = '';
        }
    }
    
    function cleanupSubscriptions() {
        if (window.chatChannels) {
            if (window.chatChannels.conversationChannel) {
                window.supabase.removeChannel(window.chatChannels.conversationChannel);
            }
            if (window.chatChannels.messageChannel) {
                window.supabase.removeChannel(window.chatChannels.messageChannel);
            }
        }
    }
});
