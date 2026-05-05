      subroutine yield_control(nodenumber)
c --
c -- This subroutine calculates the green time for each approach if the
c -- intersection has yield control.
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
	  integer i1, i2, nodenumber
	  real g1,sumgreen


! --
! -- set the green for each approach and each movement according to the
! -- proportion of the queue length on the approach to the total queue
! -- length on all approaches.
! --
      
      i1=backpointr(nodenumber)
      i2=backpointr(nodenumber+1)-1
      total_volume=0
      do i=i1,i2
         il=BackToForLink(i)
!potential inefficiency: no need for total_volume nov	
         total_volume=total_volume+vehicle_queue(il)
      enddo
! --
!      if(total_volume.lt.1) then
        do i=i1,i2
		  do j=1,llink(BackToForLink(i),nu_mv+1)
		    green(BackToForLink(i),j)=tii*60
		  enddo
        enddo
!	  else
!	    sumgreen = 0.0
!        do i=i1,i2
!          il=BackToForLink(i)
!          g1=(tii*60*vehicle_queue(il)/total_volume)
!          g2=ifix(tii*60*vehicle_queue(il)/total_volume)
!		  call random_number(rr)
!		  if(rr.lt.(g1-g2)) then
!            do j=1,llink(il,nu_mv+1)
!             green(il,j)=g2+1
!            enddo
!		  else
!            do j=1,llink(il,nu_mv+1)
!             green(il,j)=g2
!            enddo
!		  endif
!		  sumgreen=sumgreen+green(il,1)
!        enddo

!	  endif

      return
      end
