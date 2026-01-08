// // Add this at the top to test if JS loads
// console.log('🎯 Chat.js loaded successfully!');
// alert('Chat JS is working!'); // Remove this after testing

// // Your existing JS...
// document.addEventListener('DOMContentLoaded', function() {
//     console.log('🎯 Chat DOM loaded');
//     // ... rest of your JS
// });
/* filepath: c:\Users\Lance Joseph Lines\capstone_project\CapstoneWeb\tartanilla_admin\static\js\chat.js */
// Chat functionality
document.addEventListener('DOMContentLoaded', function() {
    // Auto-scroll to bottom of messages
    const messagesContainer = document.querySelector('.messages-container');
    if (messagesContainer) {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    // Handle message sending
    const messageInput = document.querySelector('textarea');
    const sendButton = document.querySelector('button[type="submit"]');
    
    function sendMessage() {
        const message = messageInput.value.trim();
        if (message) {
            // Add message to chat (you'll implement the actual sending logic)
            console.log('Sending message:', message);
            messageInput.value = '';
            messageInput.style.height = 'auto';
        }
    }

    // Send on Enter key (but not Shift+Enter)
    messageInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Auto-resize textarea
    messageInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
    });

    // Quick response buttons
    document.querySelectorAll('.quick-response').forEach(button => {
        button.addEventListener('click', function() {
            messageInput.value = this.textContent.trim();
            messageInput.focus();
        });
    });

    // Chat list item selection
    document.querySelectorAll('.chat-item').forEach(item => {
        item.addEventListener('click', function() {
            // Remove active class from all items
            document.querySelectorAll('.chat-item').forEach(i => i.classList.remove('active'));
            // Add active class to clicked item
            this.classList.add('active');
            
            // Load chat messages for selected user
            const userId = this.dataset.userId;
            loadChatMessages(userId);
        });
    });

    function loadChatMessages(userId) {
        // Implement chat loading logic here
        console.log('Loading chat for user:', userId);
    }

    // Real-time updates (you can integrate WebSocket here)
    function simulateTyping() {
        // Show typing indicator
        const typingIndicator = document.querySelector('.typing-indicator');
        if (typingIndicator) {
            typingIndicator.style.display = 'flex';
            setTimeout(() => {
                typingIndicator.style.display = 'none';
            }, 3000);
        }
    }

    // Simulate incoming message
    function addIncomingMessage(message, timestamp) {
        const messagesContainer = document.querySelector('.messages-container');
        const messageElement = document.createElement('div');
        messageElement.className = 'flex justify-start chat-message';
        messageElement.innerHTML = `
            <div class="max-w-xs lg:max-w-md">
                <div class="bg-white border border-gray-200 rounded-lg px-4 py-2">
                    <p class="text-sm text-gray-800">${message}</p>
                </div>
                <p class="text-xs text-gray-500 mt-1">${timestamp}</p>
            </div>
        `;
        messagesContainer.appendChild(messageElement);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
});