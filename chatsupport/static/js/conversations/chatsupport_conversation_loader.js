document.addEventListener('DOMContentLoaded', () => {
    const currentUserId = window.adminUserId;
    if (!currentUserId) return;

    // Default filters with better persistence
    window.currentRoleFilter = window.currentRoleFilter || null;  // all roles
    window.currentStatusFilter = window.currentStatusFilter || "open";  // default to open conversations
    window.activeConversationId = window.activeConversationId || null;

    async function loadSupportConversations(roleFilter = null, statusFilter = "open") {
        // Store current filters before any changes
        window.currentRoleFilter = roleFilter;
        window.currentStatusFilter = statusFilter;
        
        const conversationsList = document.getElementById('conversationsList');
        if (!conversationsList) return;
        
        // Show loading indicator
        conversationsList.innerHTML = '<div class="text-center py-8 text-gray-500">Loading conversations...</div>';

        try {
            // First, fetch basic conversation data
            let query = window.supabase
                .from('support_conversations')
                .select('id, user_id, admin_id, subject, status, created_at, updated_at')
                .eq('admin_id', currentUserId);

            // Apply status filter
            if (statusFilter) {
                if (statusFilter.includes(',')) {
                    const statuses = statusFilter.split(',').map(s => s.trim());
                    query = query.in('status', statuses);
                } else {
                    query = query.eq('status', statusFilter);
                }
            }

            // Get conversations
            const { data: conversations, error } = await query;
            
            if (error || !conversations || conversations.length === 0) {
                displayNoConversationsMessage(conversationsList, roleFilter, statusFilter);
                return;
            }

            // console.log(`Fetched ${conversations.length} conversations with status "${statusFilter}" and role filter "${roleFilter || 'all'}"`);
            
            // Get unique user IDs from conversations
            const userIds = [...new Set(conversations.map(conv => conv.user_id))];
            
            // Fetch user profiles using the new public_user_profiles view
            if (userIds.length > 0) {
                const { data: userProfiles, error: profilesError } = await window.supabase
                    .from('public_user_profiles')
                    .select('*')
                    .in('id', userIds);
                    
                if (profilesError) {
                    console.error("Error fetching profiles:", profilesError);
                } else {
                    // console.log(`Found ${userProfiles?.length || 0} user profiles`);
                    
                    // Create a map for quick lookup
                    const profileMap = {};
                    if (userProfiles) {
                        userProfiles.forEach(profile => {
                            profileMap[profile.id] = profile;
                        });
                    }
                    
                    // Add profile data to each conversation
                    conversations.forEach(conv => {
                        conv.user = profileMap[conv.user_id] || {
                            id: conv.user_id,
                            name: `User ${conv.user_id.substring(0, 8)}...`,
                            email: null,
                            role: 'Unknown'
                        };
                    });
                }
            }
            
            // Apply role filter if specified (after user data is loaded)
            let filteredConversations = [...conversations]; // Clone array to avoid mutations
            
            if (roleFilter && roleFilter !== 'all') {
                filteredConversations = conversations.filter(conv => 
                    conv.user && conv.user.role && conv.user.role.toLowerCase() === roleFilter.toLowerCase()
                );
                
                // console.log(`Filtered to ${filteredConversations.length} conversations with role "${roleFilter}"`);
                
                if (filteredConversations.length === 0) {
                    displayNoConversationsMessage(conversationsList, roleFilter, statusFilter);
                    return;
                }
            }

            // Add unread message counts
            await addUnreadCounts(filteredConversations, currentUserId);
            
            // Dispatch event with conversations data
            document.dispatchEvent(new CustomEvent('supportConversationsLoaded', {
                detail: { 
                    conversations: filteredConversations,
                    statusFilter: statusFilter,
                    roleFilter: roleFilter
                }
            }));
            
        } catch (err) {
            console.error("Error loading conversations:", err);
            displayNoConversationsMessage(conversationsList, roleFilter, statusFilter);
        }
    }
    
    // ADD THIS FUNCTION - it was missing from your code
    async function addUnreadCounts(conversations, currentUserId) {
        try {
            const conversationIds = conversations.map(conv => conv.id);
            
            if (conversationIds.length > 0) {
                const { data: unreadMessages, error: messagesError } = await window.supabase
                    .from('support_messages')
                    .select('id, support_conversation_id')
                    .eq('is_read', false)
                    .neq('sender_id', currentUserId)
                    .in('support_conversation_id', conversationIds);
                    
                if (!messagesError && unreadMessages) {
                    const unreadCounts = {};
                    unreadMessages.forEach(msg => {
                        const convId = msg.support_conversation_id;
                        unreadCounts[convId] = (unreadCounts[convId] || 0) + 1;
                    });
                    
                    conversations.forEach(conv => {
                        conv.unread_count = unreadCounts[conv.id] || 0;
                    });
                } else {
                    conversations.forEach(conv => {
                        conv.unread_count = 0;
                    });
                }
            }
        } catch (err) {
            console.error("Error adding unread counts:", err);
            conversations.forEach(conv => {
                conv.unread_count = 0;
            });
        }
    }

    // Helper function to display "No conversations" message
    function displayNoConversationsMessage(container, roleFilter, statusFilter) {
        let message = 'No support conversations found';
        
        if (statusFilter === 'open') {
            message = roleFilter && roleFilter !== 'all' 
                ? `No active ${roleFilter} support tickets` 
                : 'No active support tickets';
        } else if (statusFilter === 'resolved,closed') {
            message = roleFilter && roleFilter !== 'all' 
                ? `No resolved ${roleFilter} support tickets` 
                : 'No resolved support tickets';
        }
        
        container.innerHTML = `
            <div class="text-center py-12 px-4">
                <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                        d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
                <h3 class="mt-2 text-sm font-medium text-gray-900">No conversations</h3>
                <p class="mt-1 text-sm text-gray-500">${message}</p>
            </div>
        `;
        
        // Also reset the messages area
        const messagesContainer = document.getElementById('messagesContainer');
        if (messagesContainer) {
            messagesContainer.innerHTML = `
                <div class="flex flex-col items-center justify-center h-full text-center">
                    <svg class="w-16 h-16 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" 
                            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                    <h3 class="mt-2 text-sm font-medium text-gray-900">No active conversation</h3>
                    <p class="mt-1 text-sm text-gray-500">No conversations available for this filter.</p>
                </div>
            `;
        }
        
        // Reset chat header
        const chatHeader = document.querySelector('.chat-header');
        if (chatHeader) {
            chatHeader.innerHTML = `
                <img src="/static/img/TarTrack Logo_sakto.png" alt="User Profile" class="w-10 h-10 rounded-full mr-3 object-cover">
                <div class="flex-1">
                    <h2 class="text-lg font-semibold text-[#561c24]">No conversations</h2>
                    <p class="text-sm text-gray-600">No support tickets found</p>
                </div>
            `;
        }
        
        // Disable message input
        const messageForm = document.getElementById('messageForm');
        if (messageForm) {
            messageForm.classList.add('opacity-50', 'pointer-events-none');
        }
        
        const messageInput = document.getElementById('messageInput');
        if (messageInput) {
            messageInput.disabled = true;
        }
    }

    // Initial load - default to open conversations
    loadSupportConversations(null, 'open');

    // Reload on event
    document.addEventListener('reloadSupportConversations', () => {
        loadSupportConversations(window.currentRoleFilter, window.currentStatusFilter);
    });

    // Set up status tab click handlers
    const statusTabs = document.querySelectorAll('[data-status]');
    statusTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // Update UI
            statusTabs.forEach(t => {
                t.classList.remove('text-[#561c24]', 'border-b-2', 'border-[#561c24]');
                t.classList.add('text-gray-500');
            });
            tab.classList.remove('text-gray-500');
            tab.classList.add('text-[#561c24]', 'border-b-2', 'border-[#561c24]');
            
            // Store new status filter
            const newStatusFilter = tab.dataset.status;
            
            // Load conversations with new status filter but keep current role filter
            loadSupportConversations(window.currentRoleFilter, newStatusFilter);
        });
    });
    
    // Set up role tab click handlers
    const roleTabs = document.querySelectorAll('[data-role]');
    roleTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // Update UI
            roleTabs.forEach(t => {
                t.classList.remove('text-[#561c24]', 'border-b-2', 'border-[#561c24]');
                t.classList.add('text-gray-500');
            });
            tab.classList.remove('text-gray-500');
            tab.classList.add('text-[#561c24]', 'border-b-2', 'border-[#561c24]');
            
            // Get new role filter value
            const newRoleFilter = tab.dataset.role === 'all' ? null : tab.dataset.role;
            
            // Load conversations with new role filter but keep current status filter
            loadSupportConversations(newRoleFilter, window.currentStatusFilter);
        });
    });
});