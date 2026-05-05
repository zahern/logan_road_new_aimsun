        subroutine hot_lane_choice(j)

c --
c -- This subroutine is to determine whether the user will use the HOT lane or not 
c -- based on the current information available from the KSP algorithm.
c -- It compares the generalized cost of the k-paths of two path sets:
c -- one of them does not include HOT lanes and the other include HOT lanes.
c --
      use muc_mod


      kpaths=Kay

      joccup=ioc(j)

      ifrom=idnod(isec(j))

!	if(iteration.eq.0) then
!      ifrom=idnod(isec(j))
!      else
!      ifrom=origin(jorigin(j))
!	endif

      ito=MasterDest(jdest(j))

      ict = 1


        move_st=ForToBackLink(isec(j))-backpointr(ifrom)+1

!	if(iteration.eq.0) then
!        move_st=ForToBackLink(isec(j))-backpointr(ifrom)+1
!      else
!        move_st=backpointr(ifrom+1)-backpointr(ifrom)+1
!	endif   



!	  gen_cost_min=20000
        gen_cost_min=2000000

        do iiu=1,no_link_type
           do kk=1,kpaths

           generalized_cost=labeloutCost(iiu,joccup,
     *                           ito,ifrom,ict,kk,move_st)

           if(generalized_cost.LT.gen_cost_min) then
               gen_cost_min=Generalized_cost
               lt(j)=iiu
               iuserpath(j)=kk
           endif
           enddo
         enddo

         return
         end


