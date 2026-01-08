document.addEventListener('DOMContentLoaded', () => {
    // Get current user ID from global variable
    const currentUserId = window.adminUserId;
    console.log("Using admin user ID:", currentUserId);
    
    if (!currentUserId || currentUserId === "") {
        console.error('User ID not available or empty');
        
        // Show login prompt in the conversations list
        const conversationsList = document.getElementById('conversationsList');
        if (conversationsList) {
            conversationsList.innerHTML = `
                <div class="text-center py-12 px-4">
                    <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" 
                            d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                    </svg>
                    <h3 class="mt-2 text-sm font-medium text-gray-900">Authentication required</h3>
                    <p class="mt-1 text-sm text-gray-500">You must be logged in to view conversations.</p>
                </div>`;
        }
        return;
    }
    
    // Fetch initial conversations and set up real-time listener
    loadConversations();
    
    // Subscribe to conversation changes
    setupConversationSubscription();
    
    // Event to reload conversations (can be triggered from elsewhere)
    document.addEventListener('reloadConversations', loadConversations);
    
    async function loadConversations() {
        try {
            // Get the container to update
            const conversationsList = document.getElementById('conversationsList');
            if (!conversationsList) return;
            
            // Loading state
            conversationsList.innerHTML = '<div class="text-center py-8 text-gray-500">Loading conversations...</div>';
            
            // Step 1: Get conversations with joined user data
            const { data: conversations, error: convsError } = await window.supabase
                .from('conversations')
                .select(`
                    id, 
                    created_at, 
                    updated_at,
                    user1_id,
                    user2_id,
                    user1:user1_id (id, name, email, role, profile_photo_url),
                    user2:user2_id (id, name, email, role, profile_photo_url)
                `)
                .or(`user1_id.eq.${currentUserId},user2_id.eq.${currentUserId}`);
            
            if (convsError) {
                console.error('Error loading conversations:', convsError);
                conversationsList.innerHTML = '<div class="text-center py-4 text-red-500">Error loading conversations</div>';
                return;
            }
            
            // Check if we have any conversations
            if (!conversations || conversations.length === 0) {
                // Handle empty state
                conversationsList.innerHTML = `
                    <div class="text-center py-12 px-4">
                        <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" 
                                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                        </svg>
                        <h3 class="mt-2 text-sm font-medium text-gray-900">No conversations</h3>
                        <p class="mt-1 text-sm text-gray-500">Start a new conversation by clicking the "New Chat" button.</p>
                    </div>`;
                return;
            }
            
            // Step 2: Enrich conversations with last messages and unread counts
            const enrichedConversations = await Promise.all(conversations.map(async (conv) => {
                // Get the latest message for this conversation
                const { data: messages, error: msgError } = await window.supabase
                    .from('messages')
                    .select('message_text, created_at')
                    .eq('conversation_id', conv.id)
                    .eq('is_deleted', false)
                    .order('created_at', { ascending: false })
                    .limit(1);
                    
                if (msgError) {
                    console.error('Error fetching messages:', msgError);
                }
                
                // Get unread messages count
                const { count, error: countError } = await window.supabase
                    .from('messages')
                    .select('id', { count: 'exact', head: true })
                    .eq('conversation_id', conv.id)
                    .eq('is_read', false)
                    .eq('is_deleted', false)
                    .neq('sender_id', currentUserId);
                    
                if (countError) {
                    console.error('Error counting unread messages:', countError);
                }
                
                // Add last message and unread count to the conversation object
                return {
                    ...conv,
                    last_message: messages && messages.length > 0 ? messages[0].message_text : "No messages yet",
                    last_message_time: messages && messages.length > 0 ? messages[0].created_at : conv.created_at,
                    unread_count: count || 0
                };
            }));
            
            // Step 3: Sort conversations by most recent message
            enrichedConversations.sort((a, b) => {
                // Sort by last message time, falling back to conversation created time
                const timeA = a.last_message_time || a.created_at;
                const timeB = b.last_message_time || b.created_at;
                return new Date(timeB) - new Date(timeA);
            });
            
            // We have conversations, dispatch event to update UI
            document.dispatchEvent(new CustomEvent('conversationsLoaded', { 
                detail: { conversations: enrichedConversations }
            }));
            
        } catch (err) {
            console.error('Unexpected error loading conversations:', err);
            const conversationsList = document.getElementById('conversationsList');
            if (conversationsList) {
                conversationsList.innerHTML = '<div class="text-center py-4 text-red-500">An unexpected error occurred</div>';
            }
        }
    }
    
    function setupConversationSubscription() {
        // Subscribe to changes in the conversations table
        const conversationSubscription = window.supabase
            .channel('public:conversations')
            .on('postgres_changes', { 
                event: '*', 
                schema: 'public', 
                table: 'conversations',
                filter: `user1_id=eq.${currentUserId} OR user2_id=eq.${currentUserId}`
            }, payload => {
                console.log('Conversation change detected:', payload);
                // Reload conversations when there's a change
                loadConversations();
            })
            .subscribe();
            
        // Subscribe to changes in messages that might affect conversation list
        const messageSubscription = window.supabase
            .channel('public:messages')
            .on('postgres_changes', { 
                event: 'INSERT', 
                schema: 'public', 
                table: 'messages'
            }, payload => {
                console.log('New message detected:', payload);
                // We need to check if this message belongs to our conversation
                // but for simplicity, just reload conversations to update latest message
                loadConversations();
            })
            .subscribe();
            
        // Clean up subscriptions when page is unloaded
        window.addEventListener('beforeunload', () => {
            window.supabase.removeChannel(conversationSubscription);
            window.supabase.removeChannel(messageSubscription);
        });
    }
});