import pickle

NUM_LETTERS = 5

def main():
    valid_words = []
    with open('all_words.txt') as f:
        for line in f:
            word = line.strip()
            # check length is NUM_LETTERS
            if len(word) != NUM_LETTERS: continue
            
            # check for duplicate letters
            chars = set()
            for char in word: 
                chars.add(char)
            if len(chars) == NUM_LETTERS: valid_words.append(word)
    
    with open(f"{NUM_LETTERS}-letter_words.pkl", 'wb') as output_file:
        pickle.dump(valid_words, output_file, pickle.HIGHEST_PROTOCOL)            

if __name__ == "__main__":
    main()