use sha2::{Sha256, Digest};

pub fn normalize_prompt(prompt: &str) -> String {
    let lowercase = prompt.to_lowercase();
    let words: Vec<&str> = lowercase.split_whitespace().collect();
    words.join(" ")
}

pub fn hash_prompt(prompt: &str) -> String {
    let normalized = normalize_prompt(prompt);
    let mut hasher = Sha256::new();
    hasher.update(normalized.as_bytes());
    format!("{:x}", hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_prompt() {
        assert_eq!(normalize_prompt("  Hello   World  \n"), "hello world");
        assert_eq!(normalize_prompt("A B C"), "a b c");
    }

    #[test]
    fn test_hash_prompt() {
        let h1 = hash_prompt("  Hello   World  \n");
        let h2 = hash_prompt("hello world");
        assert_eq!(h1, h2);
    }
}
