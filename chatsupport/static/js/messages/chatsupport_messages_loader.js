document.addEventListener('DOMContentLoaded', () => {
    window.activeSupportConversationId = null;
    
    window.loadSupportMessages = async function(conversationId) {
        const messagesContainer = document.getElementById('messagesContainer');
        if (!messagesContainer) return;
        
        // Store the active conversation ID globally
        window.activeSupportConversationId = conversationId;
        
        messagesContainer.innerHTML = '<div class="text-center py-8 text-gray-500">Loading messages...</div>';
        
        try {
            const { data: messages, error } = await window.supabase
                .from('support_messages')
                .select('id, sender_id, message_text, created_at, is_read')
                .eq('support_conversation_id', conversationId)
                .order('created_at', { ascending: true });
                
            if (error) throw error;
            
            // Clear loading message
            messagesContainer.innerHTML = '';
            
            // Check if no messages
            if (!messages || messages.length === 0) {
                messagesContainer.innerHTML = `
                    <div class="flex flex-col items-center justify-center h-full text-center py-12">
                        <svg class="w-16 h-16 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                        </svg>
                        <h3 class="mt-2 text-sm font-medium text-gray-900">No messages yet</h3>
                        <p class="mt-1 text-sm text-gray-500">Start the conversation by sending a message below.</p>
                    </div>
                `;
                return;
            }
            
            // Group messages by date for better visual separation
            let currentDate = '';
            
            // Render all messages
            messages.forEach(msg => {
                const isCurrentUser = msg.sender_id === window.adminUserId;
                
                // Format the time with our smart formatter
                const formattedTime = window.formatMessageTime ? 
                    window.formatMessageTime(msg.created_at) : 
                    new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                
                // Check if we need a date separator
                const msgDate = new Date(msg.created_at);
                const dateStr = msgDate.toLocaleDateString();
                
                if (dateStr !== currentDate) {
                    currentDate = dateStr;
                    
                    // Add a date separator
                    const dateSeparator = document.createElement('div');
                    dateSeparator.className = 'py-2 px-4 flex justify-center';
                    
                    // Format the date separator nicely
                    let dateDisplay;
                    const today = new Date();
                    const yesterday = new Date(today);
                    yesterday.setDate(yesterday.getDate() - 1);
                    
                    if (dateStr === today.toLocaleDateString()) {
                        dateDisplay = 'Today';
                    } else if (dateStr === yesterday.toLocaleDateString()) {
                        dateDisplay = 'Yesterday';
                    } else {
                        dateDisplay = msgDate.toLocaleDateString(undefined, {
                            weekday: 'long',
                            month: 'short',
                            day: 'numeric',
                            year: msgDate.getFullYear() !== today.getFullYear() ? 'numeric' : undefined
                        });
                    }
                    
                    dateSeparator.innerHTML = `
                        <div class="bg-gray-100 text-gray-500 text-xs px-3 py-1 rounded-full">
                            ${dateDisplay}
                        </div>
                    `;
                    
                    messagesContainer.appendChild(dateSeparator);
                }
                
                // Create message element
                const messageDiv = document.createElement('div');
                messageDiv.className = `py-1 px-4 ${isCurrentUser ? 'flex justify-end' : ''}`;
                messageDiv.dataset.messageId = msg.id;
                
                messageDiv.innerHTML = `
                    <div class="max-w-[70%] rounded-lg p-3 ${isCurrentUser ? 'bg-[#561c24] text-white rounded-tr-none' : 'bg-gray-100 rounded-tl-none'}">
                        <p class="whitespace-pre-wrap break-words">${msg.message_text}</p>
                        <div class="text-xs mt-1 ${isCurrentUser ? 'text-gray-200' : 'text-gray-500'} text-right">
                            ${formattedTime}
                            ${isCurrentUser ? `<span class="ml-1">${msg.is_read ? '✓✓' : '✓'}</span>` : ''}
                        </div>
                    </div>
                `;
                
                messagesContainer.appendChild(messageDiv);
            });
            
            // Scroll to bottom after adding messages
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
            
            // Mark messages as read
            await window.supabase
                .from('support_messages')
                .update({ is_read: true })
                .eq('support_conversation_id', conversationId)
                .neq('sender_id', window.adminUserId);
            
            // Dispatch event to update sidebar badge
            document.dispatchEvent(new CustomEvent('messagesMarkedRead'));
            
        } catch (err) {
            console.error('Error loading messages:', err);
            messagesContainer.innerHTML = '<div class="text-center py-4 text-red-500">Error loading messages</div>';
        }
    };
    
    // Set initial state when no conversation is selected
    const messagesContainer = document.getElementById('messagesContainer');
    if (messagesContainer) {
        messagesContainer.innerHTML = `
            <div class="flex flex-col items-center justify-center h-full text-center">
                <svg class="w-16 h-16 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" 
                        d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
                <h3 class="mt-2 text-sm font-medium text-gray-900">Select a conversation</h3>
                <p class="mt-1 text-sm text-gray-500">Choose a conversation from the list or start a new one.</p>
            </div>
        `;
    }
    
    // Listen for conversation selection
    document.addEventListener('supportConversationSelected', (event) => {
        window.loadSupportMessages(event.detail.conversationId);
    });
});