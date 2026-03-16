#!/bin/bash
# Quick test to show AI mode in action

echo "🤖 Testing AI Mode Shadow IT Blocker"
echo "===================================="
echo ""
echo "This will show the difference between basic and AI mode"
echo ""

# Test with basic mode first
echo "1. BASIC MODE - Testing dropbox.com:"
echo "   - Only blocks if in the list"
echo "   - Simple 'BLOCKED' message"
echo ""

# Test with AI mode
echo "2. AI MODE - Testing dropbox.com:"
echo "   - Analyzes risk in real-time"
echo "   - Shows risk score and reasons"
echo "   - Suggests alternatives"
echo ""

echo "To see the AI mode in action, run:"
echo ""
echo "  sudo ./setup_blocker.sh --ai"
echo ""
echo "Then try visiting:"
echo "  • dropbox.com (file sharing risk)"
echo "  • chat.openai.com (AI tool risk)"
echo "  • github.com (lower risk, might be allowed)"
echo "  • randomnewsite2024.com (unknown site - AI will analyze)"
echo ""
echo "The AI will show detailed analysis for each!"