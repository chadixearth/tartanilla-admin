/**
 * Review Display Name Fix
 * 
 * This function properly handles the display of reviewer names based on the is_anonymous flag.
 * The key fix is checking for explicit boolean true value instead of truthy values.
 */

function getReviewDisplayName(review) {
    console.log('getReviewDisplayName called with review:', review);
    console.log('is_anonymous value:', review.is_anonymous, 'type:', typeof review.is_anonymous);
    
    // The key fix: check for explicit boolean true value
    if (review.is_anonymous === true) {
        console.log('Review is anonymous, returning "Anonymous"');
        return 'Anonymous';
    }
    
    // If not anonymous, return the actual name
    const displayName = review.reviewer_name || review.name || 'Tourist';
    console.log('Review is not anonymous, returning:', displayName);
    return displayName;
}

/**
 * Enhanced review rendering function that uses the fixed getReviewDisplayName
 */
function renderReview(review) {
    const displayName = getReviewDisplayName(review);
    const rating = Math.max(0, Math.min(5, parseInt(review.rating || 0)));
    const stars = '<i class="fas fa-star"></i>'.repeat(rating) + 
                  '<i class="far fa-star"></i>'.repeat(5 - rating);
    
    return `
        <div class="border border-gray-200 rounded-lg p-3">
            <div class="flex items-center justify-between">
                <div class="font-medium text-gray-800">${displayName}</div>
                <div class="text-yellow-500 text-xs">${stars}</div>
            </div>
            ${review.comment ? `<div class="mt-2 text-sm text-gray-700">${review.comment}</div>` : ''}
            ${review.created_at ? `<div class="mt-1 text-xs text-gray-400">${new Date(review.created_at).toLocaleString()}</div>` : ''}
        </div>
    `;
}

/**
 * Debug function to test the is_anonymous flag handling
 */
function debugAnonymousFlag() {
    console.log('=== Testing is_anonymous flag handling ===');
    
    const testCases = [
        { is_anonymous: true, reviewer_name: 'John Doe', expected: 'Anonymous' },
        { is_anonymous: false, reviewer_name: 'Jane Smith', expected: 'Jane Smith' },
        { is_anonymous: 'true', reviewer_name: 'Bob Wilson', expected: 'Bob Wilson' }, // String 'true' should not be anonymous
        { is_anonymous: 1, reviewer_name: 'Alice Brown', expected: 'Alice Brown' }, // Number 1 should not be anonymous
        { is_anonymous: null, reviewer_name: 'Charlie Davis', expected: 'Charlie Davis' },
        { is_anonymous: undefined, reviewer_name: 'Eve Miller', expected: 'Eve Miller' }
    ];
    
    testCases.forEach((testCase, index) => {
        const result = getReviewDisplayName(testCase);
        const passed = result === testCase.expected;
        console.log(`Test ${index + 1}: ${passed ? 'PASS' : 'FAIL'}`);
        console.log(`  Input: is_anonymous=${testCase.is_anonymous} (${typeof testCase.is_anonymous}), reviewer_name=${testCase.reviewer_name}`);
        console.log(`  Expected: ${testCase.expected}, Got: ${result}`);
    });
    
    console.log('=== End of tests ===');
}

// Export functions for use in other scripts
window.getReviewDisplayName = getReviewDisplayName;
window.renderReview = renderReview;
window.debugAnonymousFlag = debugAnonymousFlag;