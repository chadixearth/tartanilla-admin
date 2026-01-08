document.addEventListener('DOMContentLoaded', () => {
    const currentUserId = window.adminUserId;
    let activeConversationId = null;
    let activeOtherUser = null;
    let lastMessageTimestamp = null;
    const MESSAGE_LIMIT = 20;
    
    // Listen for conversation selection events
    document.addEventListener('conversationSelected', (event) => {
        activeConversationId = event.detail.conversationId;
        activeOtherUser = event.detail.otherUser;
        lastMessageTimestamp = null; // Reset for new conversation
        
        // Update chat header with user info
        updateChatHeader(activeOtherUser);
        
        // Load messages for this conversation
        loadMessages();
        
        // Mark messages as read
        markMessagesAsRead();
    });
    
    // Function to update the chat header
    function updateChatHeader(user) {
        const chatHeader = document.querySelector('.chat-header');
        if (!chatHeader) return;
        
        const nameElement = chatHeader.querySelector('h2');
        const roleElement = chatHeader.querySelector('.text-sm');
        
        if (nameElement) nameElement.textContent = user.name || 'Unknown User';
        if (roleElement) roleElement.textContent = user.role || '';
        
        // Update user photo if available
        const userPhotoElement = chatHeader.querySelector('img');
        if (userPhotoElement) {
            userPhotoElement.src = user.profile_photo_url || '/static/img/TarTrack Logo_sakto.png';
            userPhotoElement.onerror = () => {
                userPhotoElement.src = '/static/img/TarTrack Logo_sakto.png';
            };
        }
    }
    
    // Function to load messages for active conversation
    async function loadMessages(isLoadingMore = false) {
        if (!activeConversationId) return;
        
        const messagesContainer = document.getElementById('messagesContainer');
        if (!messagesContainer) return;
        
        // Only show loading indicator on initial load
        if (!isLoadingMore) {
            messagesContainer.innerHTML = '<div class="text-center py-8">Loading messages...</div>';
        }
        
        try {
            // Build query
            let query = window.supabase
                .from('messages')
                .select('*')
                .eq('conversation_id', activeConversationId)
                .eq('is_deleted', false)
                .order('created_at', { ascending: false })
                .limit(MESSAGE_LIMIT);
                
            // For pagination - only fetch messages older than the last one
            if (isLoadingMore && lastMessageTimestamp) {
                query = query.lt('created_at', lastMessageTimestamp);
            }
            
            // Execute query
            const { data: messages, error } = await query;
            
            if (error) throw error;
            
            // If first load or no more messages, replace content
            if (!isLoadingMore) {
                messagesContainer.innerHTML = '';
                
                // Add "load more" button if we have results
                if (messages && messages.length === MESSAGE_LIMIT) {
                    const loadMoreButton = document.createElement('button');
                    loadMoreButton.textContent = 'Load earlier messages';
                    loadMoreButton.className = 'w-full text-center py-2 text-sm text-gray-500 hover:text-gray-700';
                    loadMoreButton.addEventListener('click', () => loadMessages(true));
                    messagesContainer.appendChild(loadMoreButton);
                }
            } else {
                // Remove old load more button if it exists
                const oldButton = messagesContainer.querySelector('button');
                if (oldButton) messagesContainer.removeChild(oldButton);
            }
            
            // Process and display messages
            if (!messages || messages.length === 0) {
                if (!isLoadingMore) {
                    // Empty state for no messages
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
                } else if (messages.length < MESSAGE_LIMIT) {
                    // No more messages to load
                    const noMoreMessages = document.createElement('div');
                    noMoreMessages.className = 'text-center py-2 text-sm text-gray-500';
                    noMoreMessages.textContent = 'No more messages';
                    messagesContainer.insertBefore(noMoreMessages, messagesContainer.firstChild);
                }
                return;
            }
            
            // Track the timestamp of the oldest message for pagination
            if (messages.length > 0) {
                lastMessageTimestamp = messages[messages.length - 1].created_at;
            }
            
            // Prepare message elements (in reverse order for proper chronological display)
            const messageElements = document.createDocumentFragment();
            
            // Add load more button if we got a full page of results
            if (isLoadingMore && messages.length === MESSAGE_LIMIT) {
                const loadMoreButton = document.createElement('button');
                loadMoreButton.textContent = 'Load earlier messages';
                loadMoreButton.className = 'w-full text-center py-2 text-sm text-gray-500 hover:text-gray-700';
                loadMoreButton.addEventListener('click', () => loadMessages(true));
                messageElements.appendChild(loadMoreButton);
            }
            
            // Sort messages for display (oldest to newest)
            messages.reverse().forEach(message => {
                const isCurrentUser = message.sender_id === currentUserId;
                const messageElement = createMessageElement(message, isCurrentUser);
                messageElements.appendChild(messageElement);
            });
            
            // Add messages to container
            if (isLoadingMore) {
                messagesContainer.insertBefore(messageElements, messagesContainer.firstChild);
            } else {
                messagesContainer.appendChild(messageElements);
                // Scroll to bottom on initial load
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            }
            
        } catch (err) {
            console.error('Error loading messages:', err);
            if (!isLoadingMore) {
                messagesContainer.innerHTML = '<div class="text-center py-4 text-red-500">Error loading messages</div>';
            }
        }
    }
    
    // Function to create a message element
    function createMessageElement(message, isCurrentUser) {
        const messageTime = formatMessageTime(new Date(message.created_at));
        
        const messageContainer = document.createElement('div');
        messageContainer.className = `message-container py-1 px-4 ${isCurrentUser ? 'flex justify-end' : ''}`;
        messageContainer.dataset.messageId = message.id;
        
        const messageContent = document.createElement('div');
        messageContent.className = `max-w-[70%] rounded-lg p-3 ${isCurrentUser ? 
            'bg-[#561c24] text-white rounded-tr-none' : 
            'bg-gray-100 rounded-tl-none'}`;
            
        messageContent.innerHTML = `
            <p class="whitespace-pre-wrap break-words">${escapeHtml(message.message_text)}</p>
            <div class="text-xs mt-1 ${isCurrentUser ? 'text-gray-200' : 'text-gray-500'} text-right">
                ${messageTime}
                ${isCurrentUser ? `<span class="ml-1">${message.is_read ? '✓✓' : '✓'}</span>` : ''}
            </div>
        `;
        
        messageContainer.appendChild(messageContent);
        return messageContainer;
    }
    
    // Helper function to format message time
    function formatMessageTime(date) {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    
    // Helper function to escape HTML
    function escapeHtml(unsafe) {
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
    
    // Function to mark messages as read
    async function markMessagesAsRead() {
        if (!activeConversationId || !currentUserId) return;
        
        try {
            // Mark all unread messages from other user as read
            const { data, error } = await window.supabase
                .from('messages')
                .update({ is_read: true })
                .eq('conversation_id', activeConversationId)
                .eq('is_read', false)
                .neq('sender_id', currentUserId);
                
            if (error) throw error;
            
        } catch (err) {
            console.error('Error marking messages as read:', err);
        }
    }
    
    // Listen for real-time message updates
    document.addEventListener('newMessageReceived', (event) => {
        const message = event.detail;
        
        // Only process if it's for the active conversation
        if (message.conversation_id === activeConversationId) {
            // Add the new message to the display
            const isCurrentUser = message.sender_id === currentUserId;
            const messageElement = createMessageElement(message, isCurrentUser);
            
            const messagesContainer = document.getElementById('messagesContainer');
            if (messagesContainer) {
                messagesContainer.appendChild(messageElement);
                // Scroll to the new message
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
                
                // If message is from other user, mark it as read
                if (!isCurrentUser) {
                    markMessagesAsRead();
                }
            }
        }
    });
});