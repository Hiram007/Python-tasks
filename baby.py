#This program will be used to test if the user is 18 or older and allowed entry into a party.
year_born = int(input("Enter the year they were born and calculate if they are 18 or older."))
if year_born > 18:
    print("Congrats, you are old enough.")
elif year_born < 18:
    print("Sorry, you are not old enough.")
