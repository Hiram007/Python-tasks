import math
#ask the user to enter the name of three products
str_prod1 = input("Enter the name of the first product: ")
str_prod2 = input("Enter the name of the second product: ")
str_prod3 = input("Enter the name of the third product: ")

#Now ask for the price of each product. Each product must have two decimal
#values.
float_prod1 = float(input("Enter the price of the first item: "))
float_prod2 = float(input("Enter the price of the second item: "))
float_prod3 = float(input("Enter the price of the Third item: ") )                   

#Calculate the total of all three products.
calc_total = float_prod1 + float_prod2 + float_prod3

#Calculate the average price of the three products
avg_total = calc_total / 3

#Then print out the following sentence after performing your calculations:
print("The Total of ",float_prod1, float_prod1, float_prod1, " is R" ,calc_total," and the average price of the items is",  "R",math.ceil(avg_total))
