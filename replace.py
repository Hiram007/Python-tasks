#Declare variables
str_sentence = "The!quick!brown!fox!jumps!over!the!lazy!dog!."
str_sentence_temp = str_sentence.replace("!", " ")

#reprint this sentence as “The quick brown fox jumps over the lazy
#dog.” using the replace() function to replace every “!” exclamation mark
#with a blank space.
print(str_sentence_temp)

#Now reprint that sentence as “THE QUICK BROWN FOX JUMPS OVER THE
#LAZY DOG.” using the upper() function
print(str_sentence_temp.upper())

#Print the sentence in reverse.
print(str_sentence_temp[::-1])
