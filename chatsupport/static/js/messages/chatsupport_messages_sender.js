document.addEventListener('DOMContentLoaded', () => {
    const messageForm = document.getElementById('messageForm');
    const messageInput = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendMessageButton');
    let activeConversationId = null;
    let activeConversationStatus = null; // Track the conversation status

    // Listen for conversation selection to enable/disable the form
    document.addEventListener('supportConversationSelected', (event) => {
        activeConversationId = event.detail.conversationId;
        activeConversationStatus = event.detail.status; // Store the status
        
        // Enable/disable based on status
        if (activeConversationStatus === 'resolved' || activeConversationStatus === 'closed') {
            disableMessageForm('This conversation is ' + activeConversationStatus);
        } else {
            enableMessageForm();
        }
    });
    
    // Function to disable message form
    function disableMessageForm(reason) {
        if (messageForm) {
            messageForm.classList.add('opacity-50', 'pointer-events-none');
            
            // Add a banner explaining why messaging is disabled
            const existingBanner = document.querySelector('.status-banner');
            if (!existingBanner) {
                const banner = document.createElement('div');
                banner.className = 'status-banner bg-gray-100 border-t border-gray-200 p-2 text-center text-sm text-gray-600';
                banner.textContent = reason;
                messageForm.parentNode.insertBefore(banner, messageForm);
            }
        }
        
        if (messageInput) {
            messageInput.disabled = true;
            messageInput.placeholder = "Messaging unavailable";
        }
        
        if (sendButton) {
            sendButton.disabled = true;
        }
    }
    
    // Function to enable message form
    function enableMessageForm() {
        if (messageForm) {
            messageForm.classList.remove('opacity-50', 'pointer-events-none');
            
            // Remove status banner if it exists
            const existingBanner = document.querySelector('.status-banner');
            if (existingBanner) {
                existingBanner.remove();
            }
        }
        
        if (messageInput) {
            messageInput.disabled = false;
            messageInput.placeholder = "Type a message...";
        }
        
        if (sendButton) {
            sendButton.disabled = false;
        }
    }

    // Listen for status changes in realtime
    document.addEventListener('conversationStatusChanged', (event) => {
        const { conversationId, newStatus } = event.detail;
        
        // If this is the active conversation, update our tracking and UI
        if (activeConversationId === conversationId) {
            activeConversationStatus = newStatus;
            
            if (newStatus === 'resolved' || newStatus === 'closed') {
                disableMessageForm('This conversation is ' + newStatus);
            } else {
                enableMessageForm();
            }
        }
    });

    if (messageForm) {
        messageForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            // Extra check to prevent sending if status is resolved/closed
            if (activeConversationStatus === 'resolved' || activeConversationStatus === 'closed') {
                return; // Don't allow sending
            }
            
            if (!activeConversationId || !window.adminUserId) return;
            const messageText = messageInput.value.trim();
            if (!messageText) return;

            messageInput.value = '';
            messageInput.disabled = true;

            try {
                // Send message to database
                const { data, error } = await window.supabase
                    .from('support_messages')
                    .insert([{
                        support_conversation_id: activeConversationId,
                        sender_id: window.adminUserId,
                        message_text: messageText,
                        is_read: false
                    }])
                    .select();
                
                if (error) throw error;
                
                // Manually reload messages
                window.loadSupportMessages(activeConversationId);
                
            } catch (err) {
                console.error('Error sending message:', err);
                // Show error message
                const errorElement = document.createElement('div');
                errorElement.className = 'text-center py-2 text-xs text-red-500';
                errorElement.textContent = 'Failed to send message. Please try again.';
                
                const messagesContainer = document.getElementById('messagesContainer');
                if (messagesContainer) {
                    messagesContainer.appendChild(errorElement);
                    setTimeout(() => {
                        if (errorElement.parentNode) {
                            errorElement.parentNode.removeChild(errorElement);
                        }
                    }, 3000);
                }
                
                // Restore message to input
                messageInput.value = messageText;
            } finally {
                messageInput.disabled = false;
                messageInput.focus();
            }
        });
    }

    if (messageInput) {
        messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                messageForm.dispatchEvent(new Event('submit'));
            }
        });
    }
});