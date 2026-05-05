      subroutine no_control(nodenumber)
c --
c -- This subroutine calculates the green time for each approach if the
c -- intersection has no control.
c --
c -- This subroutine is called from intersection_control.
c -- This subroutine does not call any other subroutines.
c --
c -- INPUT :
c -- nodenumber : the intersection number.
c --
c -- OUTPUT :
c --  green times for each approach and each movement.
c --
      use muc_mod 
c --
c -- set the green for each approach and each movement to be equal to 
c -- the length of the simulation interval (in seconds)
c --
      nm = nodenumber   !G
      i1=backpointr(nm)
      i2=backpointr(nm+1)-1
      do 10 i=i1,i2
	 do 20 j=1,llink(BackToForLink(i),nu_mv+1)
	     green(BackToForLink(i),j)=tii*60
20    continue
10    continue
      return
      end
