import pickle
from hashlib import md5

NUM_LETTERS = 5
ADDITIONAL_WORDS = ['blind', 'antsy', 'bling', 'lapis', 'chest', 'giver', 'holey', 'helps', 'mixed']
PROFANE_WORD_HASHES_TO_SKIP = ['788da20fc6ffb6e232511322ee663555', 'fea321ba42e9f3c587f652f07c7f19d4', '316928e0d260556eaccb6627f2ed657b', 'd15b0ff178b085c809d334f5c5850eab', 'f5ab462e064d758a6e082ddb6d991ac0'] # this list is an attempt at exhaustiveness for the 5-letter, no-repeated-letters word game only!

def main():
    valid_words = []
    with open('all_words.txt') as f:
        for line in f:
            word = line.strip()
            
            # check that word is not to be skipped
            if md5(word.encode("utf-8")).hexdigest() in PROFANE_WORD_HASHES_TO_SKIP: continue
            
            # check length is NUM_LETTERS
            if len(word) != NUM_LETTERS: continue
            
            # check for duplicate letters
            chars = set()
            for char in word: 
                chars.add(char)
            if len(chars) == NUM_LETTERS: valid_words.append(word)
    
    valid_words += ADDITIONAL_WORDS

    with open(f"{NUM_LETTERS}-letter_words.pkl", 'wb') as output_file:
        pickle.dump(valid_words, output_file, pickle.HIGHEST_PROTOCOL)

if __name__ == "__main__":
    main()