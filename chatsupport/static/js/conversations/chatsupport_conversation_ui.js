document.addEventListener('DOMContentLoaded', () => {
    let activeConversationId = null;

    document.addEventListener('supportConversationsLoaded', (event) => {
        const conversations = event.detail.conversations;
        const conversationsList = document.getElementById('conversationsList');
        if (!conversationsList) return;

        if (!conversations || conversations.length === 0) {
            conversationsList.innerHTML = `
                <div class="text-center py-12 px-4">
                    <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                    <h3 class="mt-2 text-sm font-medium text-gray-900">No support conversations</h3>
                    <p class="mt-1 text-sm text-gray-500">No conversations found for this filter.</p>
                </div>`;
            return;
        }

        conversationsList.innerHTML = '';
        conversations.forEach(conv => {
            // Skip conversations with no user data
            if (!conv.user) {
                console.warn('Conversation found with no user data:', conv);
                return;
            }
            
            const user = conv.user;
            const item = document.createElement('div');
            
            // Set class based on whether this is the active conversation
            item.className = `p-4 border-b border-gray-100 cursor-pointer ${
                conv.id === activeConversationId ? 'bg-[#f8f2f3]' : 'hover:bg-gray-50'
            }`;
            
            item.dataset.conversationId = conv.id; // Store the ID for easy access
            
            // Use safe property access with default values
            const userName = user.name || user.email || 'Unknown User';
            const userRole = user.role || 'No role';
            const userPhoto = user.profile_photo_url || '/static/img/TarTrack Logo_sakto.png';
            
            // Check for unread messages
            const hasUnread = conv.unread_count > 0;
            
            item.innerHTML = `
                <div class="flex items-start space-x-3">
                    <div class="relative">
                        <img src="${userPhoto}"
                            alt="${userName}" class="w-12 h-12 rounded-full object-cover"
                            onerror="this.src='/static/img/TarTrack Logo_sakto.png'">
                        ${hasUnread ? 
                            `<span class="absolute -top-1 -right-1 bg-[#ff4040] text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
                                ${conv.unread_count > 9 ? '9+' : conv.unread_count}
                            </span>` : 
                            ''}
                    </div>
                    <div class="flex-1 min-w-0">
                        <div class="flex justify-between items-center">
                            <h3 class="text-sm font-semibold ${hasUnread ? 'text-[#561c24] font-bold' : 'text-[#561c24]'} truncate">
                                ${userName}
                            </h3>
                            <span class="text-xs ${getStatusClass(conv.status)}">${conv.status}</span>
                        </div>
                        <p class="text-xs text-gray-600 mb-1">${userRole}</p>
                        <p class="text-sm ${hasUnread ? 'text-gray-900 font-semibold' : 'text-gray-700'} truncate">
                            ${conv.subject || 'No subject'}
                        </p>
                    </div>
                </div>
            `;
            
            // Add click handler
            item.addEventListener('click', () => {
                // Update active conversation
                activeConversationId = conv.id;
                
                // Mark messages as read when conversation is clicked
                markMessagesAsRead(conv.id);
                
                // Remove unread indicator immediately from UI
                const unreadBadge = item.querySelector('.absolute.-top-1.-right-1');
                if (unreadBadge) unreadBadge.remove();
                
                // Make text normal weight
                const conversationName = item.querySelector('h3');
                const conversationSubject = item.querySelector('p.text-sm');
                if (conversationName) conversationName.classList.remove('font-bold');
                if (conversationSubject) {
                    conversationSubject.classList.remove('text-gray-900', 'font-semibold');
                    conversationSubject.classList.add('text-gray-700');
                }
                
                // Update UI to show active state
                const allItems = document.querySelectorAll('#conversationsList > div[data-conversation-id]');
                allItems.forEach(el => {
                    if (el.dataset.conversationId === String(conv.id)) {
                        el.classList.remove('hover:bg-gray-50');
                        el.classList.add('bg-[#f8f2f3]');
                    } else {
                        el.classList.remove('bg-[#f8f2f3]');
                        el.classList.add('hover:bg-gray-50');
                    }
                });
                
                // Dispatch event to load messages
                document.dispatchEvent(new CustomEvent('supportConversationSelected', { 
                    detail: { 
                        conversationId: conv.id,
                        user: user,
                        subject: conv.subject || 'No subject',
                        status: conv.status
                    } 
                }));
                
                // Update chat header
                updateChatHeader(user, conv.subject || 'No subject', conv.status);
            });
            
            conversationsList.appendChild(item);
        });
    });
    
    // Function to mark all messages in a conversation as read
    async function markMessagesAsRead(conversationId) {
        try {
            await window.supabase
                .from('support_messages')
                .update({ is_read: true })
                .eq('support_conversation_id', conversationId)
                .neq('sender_id', window.adminUserId);
        } catch (err) {
            console.error('Error marking messages as read:', err);
        }
    }
    
    // Helper to get status color class
    function getStatusClass(status) {
        if (!status) return 'text-gray-500';
        
        switch(status.toLowerCase()) {
            case 'open': return 'text-green-600';
            case 'resolved': return 'text-blue-600';
            case 'closed': return 'text-gray-500';
            default: return 'text-gray-500';
        }
    }
    
    // Update chat header with user info and subject
    function updateChatHeader(user, subject, status) {
        const chatHeader = document.querySelector('.chat-header');
        if (!chatHeader) return;
        
        // Use safe property access
        const userName = user.name || user.email;
        const userRole = user.role || 'No role';
        const userPhoto = user.profile_photo_url || '/static/img/TarTrack Logo_sakto.png';
        
        chatHeader.innerHTML = `
            <img src="${userPhoto}" 
                 alt="${userName}" class="w-10 h-10 rounded-full mr-3 object-cover"
                 onerror="this.src='/static/img/TarTrack Logo_sakto.png'">
            <div class="flex-1">
                <h2 class="text-lg font-semibold text-[#561c24]">${userName}</h2>
                <div class="flex items-center">
                    <p class="text-sm text-gray-600">${userRole}</p>
                    <span class="mx-2 text-gray-400">•</span>
                    <p class="text-sm font-medium ${getStatusClass(status)}">${status || 'Unknown'}</p>
                </div>
            </div>
            <div class="text-sm text-gray-700 mr-4">${subject || ''}</div>
            <div class="flex items-center">
                <button id="statusDropdownButton" class="relative p-2 rounded-full hover:bg-gray-100 focus:outline-none">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                    </svg>
                </button>
                <div id="statusDropdown" class="absolute right-4 mt-32 w-48 bg-white rounded-md shadow-lg z-20 hidden">
                    <div class="py-1">
                        <button class="status-action w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100" data-status="open">Mark as Open</button>
                        <button class="status-action w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100" data-status="resolved">Mark as Resolved</button>
                        <button class="status-action w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100" data-status="closed">Mark as Closed</button>
                    </div>
                </div>
            </div>
        `;
        
        // Add event listener for dropdown toggle
        const dropdownButton = document.getElementById('statusDropdownButton');
        const dropdown = document.getElementById('statusDropdown');
        
        if (dropdownButton && dropdown) {
            dropdownButton.addEventListener('click', () => {
                dropdown.classList.toggle('hidden');
            });
            
            // Close dropdown when clicking elsewhere
            document.addEventListener('click', (event) => {
                if (!dropdownButton.contains(event.target) && !dropdown.contains(event.target)) {
                    dropdown.classList.add('hidden');
                }
            });
            
            // Add event listeners for status actions
            const statusActions = document.querySelectorAll('.status-action');
            statusActions.forEach(button => {
                button.addEventListener('click', () => {
                    const newStatus = button.dataset.status;
                    updateConversationStatus(activeConversationId, newStatus);
                    dropdown.classList.add('hidden');
                });
            });
        }
    }
    
    // Update the updateConversationStatus function
    async function updateConversationStatus(conversationId, newStatus) {
        if (!conversationId) return;
        
        try {
            // Update the conversation status in the database
            const { error } = await window.supabase
                .from('support_conversations')
                .update({ 
                    status: newStatus,
                    updated_at: new Date().toISOString()
                })
                .eq('id', conversationId);
            
            if (error) throw error;
            
            // Dispatch an event for the status change
            document.dispatchEvent(new CustomEvent('conversationStatusChanged', {
                detail: { conversationId, newStatus }
            }));
            
            // Add system message
            sendSystemMessage(conversationId, `Conversation marked as ${newStatus} by admin`);
            
            // Reload conversations to reflect the status change
            document.dispatchEvent(new Event('reloadSupportConversations'));
            
        } catch (err) {
            console.error('Error updating conversation status:', err);
        }
    }
    
    // Add this function to your file, inside the DOMContentLoaded event handler
    async function sendSystemMessage(conversationId, message) {
        if (!conversationId) return;
        
        try {
            // Add visual system message to the UI
            const messagesContainer = document.getElementById('messagesContainer');
            if (messagesContainer) {
                const systemMessage = document.createElement('div');
                systemMessage.className = 'py-1 px-4 flex justify-center';
                systemMessage.innerHTML = `
                    <div class="py-1 px-3 rounded-full bg-gray-100 text-gray-600 text-xs">
                        ${message}
                    </div>
                `;
                messagesContainer.appendChild(systemMessage);
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            }
            
            // Optional: Also store the system message in the database
            // Comment out if you don't want to store system messages
            /*
            await window.supabase
                .from('support_messages')
                .insert({
                    support_conversation_id: conversationId,
                    sender_id: window.adminUserId,
                    message_text: message,
                    is_read: true,
                    is_system_message: true  // You might need to add this column
                });
            */
        } catch (err) {
            console.error('Error adding system message:', err);
        }
    }
});