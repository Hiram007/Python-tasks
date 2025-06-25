#This program will be used to validate that a user enters inputs at least two names when asked to enter their full name.
fullname = input("Enter your full name.")

#Do some validation to check that the user has entered a full name. Give
#an appropriate error message if they haven’t. One of the following
#messages should be displayed based on the user’s input:
if fullname == " ":
    print("You haven’t entered anything. Please enter your full name")
elif len(fullname) < 4:
    print("Please make sure that you have entered your name and surname")
elif len(fullname) > 25:
    print("Please make sure that you have only entered your full name.")
else :
    print("Thank you for entering your name.")
    

