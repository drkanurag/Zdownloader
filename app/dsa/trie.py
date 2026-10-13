from typing import Dict, Optional, Any, List

class TrieNode:
    __slots__ = ("children", "is_end_of_word", "metadata")

    def __init__(self):
        self.children: Dict[str, "TrieNode"] = {}
        self.is_end_of_word: bool = False
        self.metadata: Optional[Any] = None

class DomainRadixTrie:
    """
    Trie (Prefix Tree) specialized for domain classification and security pattern matching.
    
    Domains are indexed in reverse segment order (e.g., 'm.youtube.com' -> ['com', 'youtube', 'm'])
    to support wildcard and subdomain matching in O(L) time, where L is the number of domain segments.
    """
    def __init__(self):
        self.root = TrieNode()

    def _split_domain(self, domain: str) -> List[str]:
        """Normalize and reverse domain segments for suffix/subdomain matching."""
        cleaned = domain.strip().lower().strip(".")
        parts = cleaned.split(".")
        parts.reverse()  # Match from TLD downwards
        return parts

    def insert(self, domain_pattern: str, metadata: Optional[Any] = None) -> None:
        """
        Insert domain pattern into Trie in O(L) time.
        Supports wildcard subdomains like '*.youtube.com'.
        """
        parts = self._split_domain(domain_pattern.replace("*.", ""))
        curr = self.root
        for part in parts:
            if part not in curr.children:
                curr.children[part] = TrieNode()
            curr = curr.children[part]
        curr.is_end_of_word = True
        curr.metadata = metadata

    def search_exact(self, domain: str) -> Optional[Any]:
        """Search exact domain match in O(L) time."""
        parts = self._split_domain(domain)
        curr = self.root
        for part in parts:
            if part not in curr.children:
                return None
            curr = curr.children[part]
        return curr.metadata if curr.is_end_of_word else None

    def match_subdomain(self, domain: str) -> Optional[Any]:
        """
        Match domain or any parent domain / wildcard match in O(L) time.
        For instance, if 'youtube.com' is in the Trie, 'music.youtube.com' matches.
        """
        parts = self._split_domain(domain)
        curr = self.root
        last_matched_metadata = None

        for part in parts:
            if part not in curr.children:
                break
            curr = curr.children[part]
            if curr.is_end_of_word:
                last_matched_metadata = curr.metadata

        return last_matched_metadata

