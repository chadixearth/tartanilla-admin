document.addEventListener('DOMContentLoaded', () => {
    const currentUserId = window.adminUserId;
    const messageForm = document.getElementById('messageForm');
    const messageInput = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendMessageButton');
    let activeConversationId = null;
    
    // Listen for conversation selection events
    document.addEventListener('conversationSelected', (event) => {
        activeConversationId = event.detail.conversationId;
        
        // Enable the form now that a conversation is selected
        if (messageForm) {
            messageForm.classList.remove('opacity-50', 'pointer-events-none');
        }
        if (messageInput) {
            messageInput.disabled = false;
            messageInput.focus();
        }
        if (sendButton) {
            sendButton.disabled = false;
        }
    });
    
    // Handle message form submission
    if (messageForm) {
        messageForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            // Don't send if no active conversation
            if (!activeConversationId || !currentUserId) {
                return;
            }
            
            const messageText = messageInput.value.trim();
            if (!messageText) return;
            
            // Clear input and disable temporarily to prevent double-sends
            messageInput.value = '';
            messageInput.disabled = true;
            if (sendButton) sendButton.disabled = true;
            
            try {
                // Send the message to the database
                const { data: newMessage, error } = await window.supabase
                    .from('messages')
                    .insert([{
                        conversation_id: activeConversationId,
                        sender_id: currentUserId,
                        message_text: messageText,
                        is_read: false
                    }])
                    .select();
                    
                if (error) throw error;
                
                // The real-time subscription will handle updating the message list
                // But we can also add it directly for immediate feedback
                if (newMessage && newMessage.length > 0) {
                    document.dispatchEvent(new CustomEvent('newMessageReceived', {
                        detail: newMessage[0]
                    }));
                }
                
            } catch (err) {
                console.error('Error sending message:', err);
                // Show error in chat area
                const messagesContainer = document.getElementById('messagesContainer');
                if (messagesContainer) {
                    const errorElement = document.createElement('div');
                    errorElement.className = 'text-center py-2 text-xs text-red-500';
                    errorElement.textContent = 'Failed to send message. Please try again.';
                    messagesContainer.appendChild(errorElement);
                    
                    // Auto-remove after 3 seconds
                    setTimeout(() => {
                        if (errorElement.parentNode) {
                            errorElement.parentNode.removeChild(errorElement);
                        }
                    }, 3000);
                    
                    // Put the failed message back in the input
                    messageInput.value = messageText;
                }
            } finally {
                // Re-enable input
                messageInput.disabled = false;
                if (sendButton) sendButton.disabled = false;
                messageInput.focus();
            }
        });
    }
    
    // Handle Enter key to send, Shift+Enter for new line
    if (messageInput) {
        messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault(); // Prevent default to avoid new line
                messageForm.dispatchEvent(new Event('submit'));
            }
        });
    }
    
    // Handle file uploads if needed - placeholder for future implementation
    const fileUpload = document.getElementById('fileUpload');
    if (fileUpload) {
        fileUpload.addEventListener('change', (e) => {
            // File upload functionality would go here
            console.log('File selected:', e.target.files);
            // This is a placeholder - you would implement file upload to storage here
        });
    }
});