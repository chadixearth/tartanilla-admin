document.addEventListener('DOMContentLoaded', () => {
    console.log('Badge script loaded, checking for prerequisites...');
    
    // Check if we can access Supabase - if not, try to initialize it
    if (!window.supabase) {
        console.log('Supabase not found, attempting to initialize...');
        // Try to initialize from environment variables if possible
        initializeSupabaseClient();
    }
    
    // Function to initialize Supabase client if needed
    function initializeSupabaseClient() {
        try {
            if (window.supabaseUrl && window.supabaseKey) {
                window.supabase = supabase.createClient(window.supabaseUrl, window.supabaseKey);
                console.log('Supabase client initialized');
                
                // Setup realtime subscriptions once Supabase is initialized
                setupRealtimeSubscriptions();
            }
        } catch (err) {
            console.error('Failed to initialize Supabase client:', err);
        }
    }
    
    // Set up robust realtime subscriptions for badge updates
    function setupRealtimeSubscriptions() {
        if (!window.supabase) return;
        const channel = window.supabase.channel('support-messages-realtime');
        
        // Listen for new messages
        channel.on('postgres_changes', {
            event: 'INSERT',
            schema: 'public',
            table: 'support_messages'
        }, (payload) => {
            console.log('Realtime: New message received', payload);
            updateChatSupportBadge();
        });
        
        // Listen for message updates (read/unread status changes)
        channel.on('postgres_changes', {
            event: 'UPDATE',
            schema: 'public',
            table: 'support_messages'
        }, (payload) => {
            console.log('Realtime: Message updated', payload);
            updateChatSupportBadge();
        });
        
        // Listen for message deletions
        channel.on('postgres_changes', {
            event: 'DELETE',
            schema: 'public',
            table: 'support_messages'
        }, (payload) => {
            console.log('Realtime: Message deleted', payload);
            updateChatSupportBadge();
        });
        
        // Listen for new/updated/deleted conversations assigned to admin
        channel.on('postgres_changes', {
            event: 'INSERT',
            schema: 'public',
            table: 'support_conversations'
        }, (payload) => {
            console.log('Realtime: New conversation', payload);
            updateChatSupportBadge();
        });
        channel.on('postgres_changes', {
            event: 'UPDATE',
            schema: 'public',
            table: 'support_conversations'
        }, (payload) => {
            console.log('Realtime: Conversation updated', payload);
            updateChatSupportBadge();
        });
        channel.on('postgres_changes', {
            event: 'DELETE',
            schema: 'public',
            table: 'support_conversations'
        }, (payload) => {
            console.log('Realtime: Conversation deleted', payload);
            updateChatSupportBadge();
        });
        
        channel.subscribe(status => {
            console.log('Realtime badge subscription status:', status);
            if (status === 'SUBSCRIBED') {
                console.log('Realtime badge subscription active');
            } else if (status === 'CLOSED') {
                console.log('Realtime badge subscription closed, attempting to reconnect...');
                // Attempt to reconnect after a delay
                setTimeout(() => setupRealtimeSubscriptions(), 5000);
            }
        });
    }
    
    // Function to update the chat support badge
    async function updateChatSupportBadge() {
        try {
            console.log('Current page:', window.location.pathname);
            console.log('Looking for chat support link...');
            
            // If Supabase is still not available, exit
            if (!window.supabase) {
                console.log('Supabase not available, cannot update badge');
                return;
            }
            
            // Get admin user ID - try multiple potential sources
            const adminUserId = window.adminUserId || window.currentUserId || window.userId;
            console.log('Admin user ID:', adminUserId);
            
            if (!adminUserId) {
                // Try to get from session if available
                try {
                    const { data: { user } } = await window.supabase.auth.getUser();
                    if (user) {
                        window.adminUserId = user.id;
                        console.log('Retrieved user ID from session:', user.id);
                    }
                } catch (e) {
                    console.log('Could not retrieve user from session');
                    return;
                }
            }
            
            if (!window.adminUserId) return;
            
            // Check if we're on the chat support page
            const isOnChatSupportPage = window.location.pathname.includes('chatsupport');
            
            // Find the chat support link
            const chatSupportItem = document.getElementById('chatSupportLink');
            console.log('Chat support item found:', !!chatSupportItem);
            
            if (!chatSupportItem) {
                console.log('Could not find chat support link in sidebar');
                return;
            }
            
            // Get all conversations for this admin
            const { data: conversations, error: convError } = await window.supabase
                .from('support_conversations')
                .select('id')
                .eq('admin_id', window.adminUserId);
                
            if (convError || !conversations || conversations.length === 0) {
                // No conversations, hide badge
                removeBadgeFromItem(chatSupportItem);
                return;
            }
            
            // Get conversation IDs
            const conversationIds = conversations.map(conv => conv.id);
            
            // Get currently active conversation ID (if any)
            const activeConversationId = window.activeSupportConversationId;
            
            // Count unread messages not sent by current admin
            let query = window.supabase
                .from('support_messages')
                .select('id, support_conversation_id')
                .eq('is_read', false)
                .neq('sender_id', window.adminUserId)
                .in('support_conversation_id', conversationIds);
                
            // If we're on the chat support page with an active conversation,
            // exclude messages from that conversation from the badge count
            if (isOnChatSupportPage && activeConversationId) {
                query = query.neq('support_conversation_id', activeConversationId);
                console.log('Excluding active conversation from badge count:', activeConversationId);
            }
            
            const { data: unreadMessages, error: msgError } = await query;
            
            if (msgError) {
                console.error('Error fetching unread messages:', msgError);
                return;
            }
            
            // Update badge with count
            const unreadCount = unreadMessages?.length || 0;
            console.log('Unread message count:', unreadCount);
            updateBadgeOnItem(chatSupportItem, unreadCount);
            
        } catch (err) {
            console.error('Error updating chat badge:', err);
        }
    }
    
    // Helper function to remove badge
    function removeBadgeFromItem(item) {
        const existingBadge = item.querySelector('.notification-badge');
        if (existingBadge) {
            existingBadge.remove();
        }
    }
    
    // Helper function to update or add badge
    function updateBadgeOnItem(item, count) {
        const badge = item.querySelector('.notification-badge') || 
                      item.querySelector('#chatSupportBadge');
        
        if (!badge) {
            console.log('Badge element not found in chat support link');
            return;
        }
        
        if (count > 0) {
            badge.textContent = count > 99 ? '99+' : count;
            badge.classList.remove('hidden');
            console.log('Badge updated with count:', count);
        } else {
            badge.classList.add('hidden');
            console.log('Badge hidden (no unread messages)');
        }
    }
    
    // Run initial update
    updateChatSupportBadge();
    
    // Only setup realtime if Supabase is available
    if (window.supabase) {
        setupRealtimeSubscriptions();
    } else {
        console.log('Supabase not available, skipping realtime setup');
    }
    
    // Update badge every 60 seconds as a fallback
    setInterval(updateChatSupportBadge, 60000);
    
    // Listen for messages being marked as read (dispatched from chat support page)
    document.addEventListener('messagesMarkedRead', () => {
        console.log('Messages marked as read, updating badge...');
        updateChatSupportBadge();
    });
});