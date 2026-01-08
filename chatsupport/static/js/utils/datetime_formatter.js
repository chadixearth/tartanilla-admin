/**
 * Format a timestamp intelligently based on how old it is:
 * - Within 24 hours: Show time only (e.g., "2:45 PM")
 * - Yesterday: Show "Yesterday" with time (e.g., "Yesterday, 3:15 PM")
 * - Within 7 days: Show day name with time (e.g., "Monday, 10:23 AM")
 * - Older: Show full date (e.g., "Aug 15, 2023, 9:30 AM")
 */
function formatMessageTime(timestamp) {
    if (!timestamp) return '';
    
    const date = new Date(timestamp);
    const now = new Date();
    
    // Check if valid date
    if (isNaN(date.getTime())) return '';
    
    // Time portion (used in all formats)
    const timeOptions = { hour: 'numeric', minute: 'numeric' };
    const timeString = date.toLocaleTimeString(undefined, timeOptions);
    
    // Calculate the difference in days
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    
    const isToday = date.getDate() === now.getDate() && 
                   date.getMonth() === now.getMonth() &&
                   date.getFullYear() === now.getFullYear();
                   
    const isYesterday = date.getDate() === yesterday.getDate() &&
                       date.getMonth() === yesterday.getMonth() &&
                       date.getFullYear() === yesterday.getFullYear();
    
    // Check if it's within the last 7 days
    const oneWeekAgo = new Date(now);
    oneWeekAgo.setDate(now.getDate() - 6); // 6 days ago plus today = 7 days
    const isWithinWeek = date >= oneWeekAgo;
    
    // Format based on how old the message is
    if (isToday) {
        return timeString;
    } else if (isYesterday) {
        return `Yesterday, ${timeString}`;
    } else if (isWithinWeek) {
        const dayName = date.toLocaleDateString(undefined, { weekday: 'long' });
        return `${dayName}, ${timeString}`;
    } else {
        // For older messages, show the full date
        const dateOptions = { month: 'short', day: 'numeric', year: 'numeric' };
        const dateString = date.toLocaleDateString(undefined, dateOptions);
        return `${dateString}, ${timeString}`;
    }
}

// Make the function available globally
window.formatMessageTime = formatMessageTime;