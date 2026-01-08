document.addEventListener('DOMContentLoaded', () => {
    const currentUserId = window.adminUserId;
    let activeConversationId = null;
    
    if (!currentUserId) return;
    
    // Listen for conversation selection
    document.addEventListener('conversationSelected', (event) => {
        activeConversationId = event.detail.conversationId;
    });
    
    // Set up real-time subscription for messages
    const messageChannel = window.supabase
        .channel('message-updates')
        .on('postgres_changes', {
            event: 'INSERT',
            schema: 'public',
            table: 'messages',
        }, handleNewMessage)
        .on('postgres_changes', {
            event: 'UPDATE',
            schema: 'public',
            table: 'messages'
        }, handleMessageUpdate)
        .subscribe();
        
    // Clean up on page unload
    window.addEventListener('beforeunload', () => {
        if (messageChannel) {
            window.supabase.removeChannel(messageChannel);
        }
    });
    
    // Handle new messages
    async function handleNewMessage(payload) {
        const message = payload.new;
        
        // Only handle messages for the active conversation or from other conversations
        if (message.conversation_id === activeConversationId) {
            // If this is not our own message
            if (message.sender_id !== currentUserId) {
                // Dispatch event to add message to UI
                document.dispatchEvent(new CustomEvent('newMessageReceived', {
                    detail: message
                }));
            }
        } else {
            // Message is for another conversation - should update unread count
            // This is handled by conversation_realtime.js
        }
    }
    
    // Handle message updates (e.g., read status)
    function handleMessageUpdate(payload) {
        const message = payload.new;
        
        // Update read status indicators
        if (message.conversation_id === activeConversationId && message.sender_id === currentUserId) {
            // Find the message element
            const messageElement = document.querySelector(`[data-message-id="${message.id}"]`);
            if (messageElement) {
                const readStatus = messageElement.querySelector('span');
                if (readStatus && message.is_read) {
                    readStatus.textContent = '✓✓'; // Double check mark for read
                }
            }
        }
    }
});