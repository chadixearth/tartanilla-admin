document.addEventListener('DOMContentLoaded', () => {
    // Set up real-time subscription for messages
    const messageChannel = window.supabase
        .channel('support-messages-realtime')
        .on('postgres_changes', {
            event: 'INSERT',
            schema: 'public',
            table: 'support_messages'
        }, handleNewMessage)
        .on('postgres_changes', {
            event: 'UPDATE',
            schema: 'public',
            table: 'support_messages'
        }, handleUpdatedMessage)
        .subscribe();
        
    // Clean up on page unload
    window.addEventListener('beforeunload', () => {
        if (messageChannel) {
            window.supabase.removeChannel(messageChannel);
        }
    });
    
    // Handle new message from real-time subscription
    function handleNewMessage(payload) {
        const message = payload.new;
        
        // Only process if it's for the active conversation and not sent by current user
        if (
            window.activeSupportConversationId === message.support_conversation_id && 
            message.sender_id !== window.adminUserId
        ) {
            addMessageToUI(message);
        }
    }
    
    // Handle updated message (e.g., read status)
    function handleUpdatedMessage(payload) {
        const message = payload.new;
        
        // Update read status in UI if needed
        if (window.activeSupportConversationId === message.support_conversation_id) {
            const messageElement = document.querySelector(`[data-message-id="${message.id}"]`);
            if (messageElement && message.sender_id === window.adminUserId) {
                const statusElement = messageElement.querySelector('.text-right span');
                if (statusElement && message.is_read) {
                    statusElement.textContent = '✓✓';
                }
            }
        }
    }
    
    // Helper function to add a message to the UI
    function addMessageToUI(message) {
        const messagesContainer = document.getElementById('messagesContainer');
        if (!messagesContainer) return;
        
        // If this is the first message, clear the "no messages" placeholder
        if (messagesContainer.querySelector('.flex-col.items-center.justify-center')) {
            messagesContainer.innerHTML = '';
        }
        
        const isCurrentUser = message.sender_id === window.adminUserId;
        const messageDiv = document.createElement('div');
        messageDiv.className = `py-1 px-4 ${isCurrentUser ? 'flex justify-end' : ''}`;
        messageDiv.dataset.messageId = message.id;
        
        messageDiv.innerHTML = `
            <div class="max-w-[70%] rounded-lg p-3 ${isCurrentUser ? 'bg-[#561c24] text-white rounded-tr-none' : 'bg-gray-100 rounded-tl-none'}">
                <p class="whitespace-pre-wrap break-words">${message.message_text}</p>
                <div class="text-xs mt-1 ${isCurrentUser ? 'text-gray-200' : 'text-gray-500'} text-right">
                    ${new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    ${isCurrentUser ? `<span class="ml-1">${message.is_read ? '✓✓' : '✓'}</span>` : ''}
                </div>
            </div>
        `;
        
        messagesContainer.appendChild(messageDiv);
        
        // Scroll to bottom
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
});